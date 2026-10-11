"""Offline reliability suite for Scheduled Free Power (post-export entry fps1; the 11 Oct 2026 incident).

Incident: the 11:00-13:00 BST scheduled session never started. The firmware start gate refuses a press at once while any
Modbus frame is queued or awaiting its reply (plus the 600 ms turnaround). The routine 10 s telemetry poll keeps the bus busy
about 20 % of the time. The package pressed at about +2 s and retried once at about +35 s, a spacing locked to the 10 s
cycle: both presses landed in a telemetry read, nothing was written, the schedule disarmed itself, and nobody was told.

The REAL package YAML (and, for the reproduction, the package as of fe1, undone exactly by the PEX layer) runs under
_ha_script_sim.py: a fail-loud interpreter of the Home Assistant script / automation subset with a virtual clock, and a model
of the dongle's start gate, transaction, timer and Modbus poll, using the busy windows measured on 11 Oct.

  [0] static        package shape (helper / script / automation counts unchanged), entity ids exist in the firmware, the
                    retried refusal texts are verbatim firmware gate texts, only safe services, no register path
  [1] incident      the package as of fe1 reproduces 11 Oct exactly (refusals at +2.6 s and +35.1 s, FAILED, no alert)
  [2] fix           the same inputs now start, verified ACTIVE, ending inside the authorised window
  [3] every phase   the poll phase swept over a whole minute x press-handling delays: the old package fails ~6 %, the new 0 %
  [4] transient     RTC correction, another write, configuration offline, a lost press: retried, bounded, then started
  [5] persistent    snapshot pending, Dump owns, NTP: refused once, no retry, an alert at once
  [6] transaction   a start that passed the gate and then failed is never retried, and alerts
  [7] window        duration clamp, the start deadline, short windows, never a press after the deadline, never a run past it
  [8] watchdog      a lost start trigger is recovered at +3 min with an alert; never while a start is still retrying
  [9] readiness     5 min before: an alert naming each blocker; silent when ready
  [10] restart      Home Assistant restart inside / after the window: recovered / MISSED, both alerted
  [11] status       ARMED -> STARTING -> ACTIVE -> COMPLETED, and FAILED
  [12] mutation     in-memory mutants of the package are each caught; equivalent rewrites survive
  [13] PEX          the fps1 declaration

Writes nothing; no Home Assistant, no network, no hardware. It proves the package's control flow against a model, not a live
Home Assistant or the dongle.
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

PKG_REL = "home-assistant/packages/ecco_free_power_schedule.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")

FAILS: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}" + (f"\n        {detail}" if detail else ""))


START = "2026-10-11 11:00:00"
ST = S.parse_local(START)
LAST = "input_text.ecco_free_power_schedule_last_result"
ARMED = "input_boolean.ecco_free_power_schedule_armed"
STATUS = "sensor.ecco_free_power_schedule_status"
SCRIPT = "script.ecco_free_power_start_scheduled"
INCIDENT_DELAYS = (0.6, 0.1)   # measured: the first press was handled ~0.6 s after HA pressed, the retry ~0.1 s


class Run:
    """One simulated schedule: Home Assistant + the package + the dongle, armed at 10:51 for START."""

    def __init__(self, text=PKG_TEXT, phase=0.0, delays=INCIDENT_DELAYS, start=START, duration=120, power=8000,
                 setup=None, arm=True, lose=(), outcome="ok", limit=8000):
        self.w = S.World(S.parse_local("2026-10-11 10:50:00"))
        self.ha = S.HA(self.w, yaml.safe_load(text))
        self.d = S.Dongle(self.w, phase=phase, handle_delays=delays, outcome=outcome)
        w = self.w
        w.set("sensor.ecco_config_maximum_grid_charge_power", str(limit))
        w.set("input_datetime.ecco_free_power_schedule_start", start)
        w.set("input_number.ecco_free_power_schedule_duration", f"{float(duration)}")
        w.set("input_number.ecco_free_power_schedule_power", f"{float(power)}")
        w.set(ARMED, "off")
        w.set(LAST, "")
        w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "off")
        self.start_ts = S.parse_local(start)
        self.end_ts = self.start_ts + duration * 60
        self.ha.start()
        for a in self.ha.automations:
            a.disabled_triggers |= set(lose)
        if setup:
            setup(self)
        w.run_until(S.parse_local("2026-10-11 10:51:00"))
        if arm:
            w.set(ARMED, "on")

    def until(self, seconds_after_start: float) -> "Run":
        self.w.run_until(self.start_ts + seconds_after_start)
        return self

    # observations
    def gate(self):
        return [(round(t - self.start_ts, 3), o) for t, o in self.d.presses]

    def presses(self):
        return [t - self.start_ts for t in self.d.press_log]

    def created(self):
        return [n for n in self.w.notification_log if n[1] == "create"]

    def last(self):
        return self.w.state(LAST)

    def status(self):
        return self.w.state(STATUS)

    def arm_left_on(self):
        return self.w.state("switch.ecco_clock_dongle_free_power_write_enable") == "on"


def old_package_text() -> str:
    import _pex  # noqa: E402  (PEX: the package as of fe1 - fps1 undone exactly, sha256-checked at each step)
    return _pex.as_of(PKG_REL, "fe1", _pex.read(PKG_REL))   # PEX: the pre-fps1 package for the reproduction


OLD_TEXT = old_package_text()

# ======================================================================================================================
print("[0] static")
# ======================================================================================================================
pkg = yaml.safe_load(PKG_TEXT)
old = yaml.safe_load(OLD_TEXT)
shape = {k: len(v) for k, v in pkg.items()}
check("the package keeps its helper, script and automation counts (1/1/2/1 helpers, 2 scripts, 3 automations, 1 template)",
      shape == {k: len(v) for k, v in old.items()} == {"input_boolean": 1, "input_datetime": 1, "input_number": 2,
                                                         "input_text": 1, "script": 2, "automation": 3, "template": 1},
      str(shape))
check("helper definitions, the cancel script and the template sensor's attributes are unchanged",
      all(pkg[k] == old[k] for k in ("input_boolean", "input_datetime", "input_number", "input_text"))
      and pkg["script"]["ecco_free_power_cancel_schedule"] == old["script"]["ecco_free_power_cancel_schedule"]
      and pkg["template"][0]["sensor"][0]["attributes"] == old["template"][0]["sensor"][0]["attributes"])
fw_names = set(re.findall(r'name: "([^"]+)"', FW_TEXT))
fw_slugs = {re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_") for n in fw_names}   # Home Assistant's slugify
used = set(re.findall(r"\b(?:binary_sensor|sensor|switch|button|number)\.ecco_clock_dongle_([a-z0-9_]+)", PKG_TEXT))
check(f"every dongle entity the package uses exists in the firmware ({len(used)} ids)", used <= fw_slugs,
      str(sorted(used - fw_slugs)))
gate_else = FW_TEXT[FW_TEXT.index("bool armed = id(free_power_write_enable).state;"):]
gate_else = gate_else[:gate_else.index("id(free_power_write_enable).turn_off();")]
fw_rejects = re.findall(r'publish_state\("(REJECTED - [^"]+)"\)', gate_else)
retried = re.findall(r"s\.startswith\('(REJECTED - [^']+)'\)", PKG_TEXT)
check(f"the {len(retried)} retried refusals are verbatim prefixes of the firmware start gate's own texts",
      len(retried) == 4 and all(any(r.startswith(p) for r in fw_rejects) for p in retried), f"{retried} vs {fw_rejects}")
check("...and they are exactly the transient ones: bus busy, RTC correction, another write, configuration offline",
      sorted(p.split(" - ")[1].split()[0] for p in retried) == ["Modbus", "RTC", "another", "inverter"])
services = set(re.findall(r"action: ([a-z_]+\.[a-z_]+)", PKG_TEXT))
check("the package calls only helper, dongle-control, script and notification services (no register or Modbus path)",
      services <= {"input_text.set_value", "input_boolean.turn_off", "number.set_value", "switch.turn_on", "switch.turn_off",
                   "button.press", "script.ecco_free_power_start_scheduled", "persistent_notification.create",
                   "persistent_notification.dismiss"}, str(sorted(services)))
check("the package never calls an ESPHome action, a Modbus service or a register write",
      not any(re.search(r"esphome|modbus|register", sv, re.I) for sv in services))

# ======================================================================================================================
print("\n[1] the incident, reproduced with the package as of fe1")
# ======================================================================================================================
r = Run(OLD_TEXT).until(180)
check("the old package presses at about +2 s and +35 s, both land in a telemetry read and are refused (bus busy)",
      [round(t) for t, _ in r.gate()] == [3, 35] and all("bus busy" in o for _, o in r.gate()), str(r.gate()))
check("...nothing is written (the start transaction never begins)", r.d.attempts == 0 and not r.d.active)
check("...the result is FAILED TO START - REJECTED - Modbus bus busy, the schedule disarms, status IDLE",
      r.last().startswith("FAILED TO START - REJECTED - Modbus bus busy") and r.w.state(ARMED) == "off"
      and r.status() == "IDLE", f"{r.last()} / {r.status()}")
check("...and no alert of any kind is raised (the gap the owner found)", r.created() == [])

# ======================================================================================================================
print("\n[2] the fix, same inputs")
# ======================================================================================================================
r = Run().until(7300)
check("the new package starts: ACTIVE verified, STARTED OK recorded, the schedule disarmed",
      r.d.successes == 1 and r.last().startswith("STARTED OK") and r.w.state(ARMED) == "off", r.last())
check("...within 40 s of the start time", r.d.started_at - r.start_ts <= 40, str(r.d.started_at - r.start_ts))
check("...the session ends within 30 s of the authorised window's end (13:00)", r.d.ends_at <= r.end_ts + 30,
      S.local_str(r.d.ends_at))
check("...no alert when it starts", r.created() == [])
check("...the write enable is never left on", not r.arm_left_on())

# ======================================================================================================================
print("\n[3] every poll phase")
# ======================================================================================================================
stats = {}
for name, text in (("old", OLD_TEXT), ("new", PKG_TEXT)):
    n = fails = worst_presses = 0
    worst_start = 0.0
    for i in range(0, 600, 5):                          # the whole minute, 0.5 s steps
        for dl in ((0.05,), (0.15,), INCIDENT_DELAYS):
            r = Run(text, phase=i / 10, delays=dl).until(720)
            n += 1
            if not r.d.active:
                fails += 1
                continue
            worst_presses = max(worst_presses, len(r.d.presses))
            worst_start = max(worst_start, r.d.started_at - r.start_ts)
            if r.arm_left_on():
                fails += 1
    stats[name] = (n, fails, worst_presses, worst_start)
n, f, wp, ws = stats["old"]
check(f"the old package fails at {f / n:.1%} of poll phases (the ~1-in-20 risk behind 11 Oct)", 0.02 <= f / n <= 0.12,
      str(stats["old"]))
n, f, wp, ws = stats["new"]
check(f"the new package starts at EVERY phase and press delay ({n} runs): at most {wp} presses, started by +{ws:.0f} s",
      f == 0 and wp <= 6 and ws <= 60, str(stats["new"]))

# ======================================================================================================================
print("\n[4] transient refusals: retried, bounded")
# ======================================================================================================================
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 49))).until(600)
check("an RTC correction running at the start (49 s) is waited out: refused as RTC, then started",
      r.d.successes == 1 and any("RTC correction" in o for _, o in r.gate()) and r.d.started_at - ST < 70, str(r.gate()))
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 95))).until(600)
check("...and one held until the 90 s breaker: started within 45 s of the lock clearing",
      r.d.successes == 1 and r.d.started_at - (ST + 95) <= 45, str(r.gate()[-2:]))
r = Run(setup=lambda x: x.d.set_offline(ST - 60, ST + 180)).until(600)
check("the dongle offline from 10:59 to 11:03: nothing pressed while offline, started once back",
      r.d.successes == 1 and all(not (ST - 60 <= ST + p < ST + 180) for p in r.presses()) and r.created() == [],
      str(r.presses()[:3]))
r = Run()
_orig_press = r.d._press


def _drop_first(entity, data, d=r.d):
    if not d.press_log:
        d.press_log.append(d.w.t)            # the first press reaches nobody (API hiccup): never acknowledged
        return
    _orig_press(entity, data)


r.w.service_handlers["button.press"] = _drop_first
r.until(600)
check("a press the dongle never acknowledges: HA disarms the switch itself and retries", r.d.successes == 1
      and len(r.d.press_log) == 2 and not r.arm_left_on(), str(r.presses()))
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 3600))).until(1200)
check("a refusal that never clears: retries stop at the deadline (start + 10 min), FAILED with an alert",
      r.d.successes == 0 and max(r.presses()) <= 600 and r.last().startswith("FAILED TO START")
      and [n[2] for n in r.created()] == ["ecco_free_power_schedule"] and not r.arm_left_on(),
      f"{max(r.presses()):.0f} {r.last()[:80]}")
check(f"...a bounded number of presses ({len(r.presses())}, at most 60), fast at first then backing off",
      len(r.presses()) <= 60 and r.presses()[8] - r.presses()[0] < 90, str(len(r.presses())))
spacing = sorted({round(b - a, 1) for a, b in zip(r.presses(), r.presses()[1:])})
check(f"...with uneven spacing that never matches the 10 s poll (spacings {spacing})",
      len(spacing) >= 3 and all(abs(s_ - round(s_ / 10) * 10) > 0.5 for s_ in spacing))

# ======================================================================================================================
print("\n[5] persistent refusals: no retry, alert at once")
# ======================================================================================================================
for label, flag, needle in (("a saved snapshot pending restore", "snapshot", "saved snapshot"),
                            ("Dump to Grid owning the inverter", "dump", "Dump to Grid"),
                            ("no valid NTP time", "ntp_bad", "NTP")):
    r = Run(setup=lambda x, f_=flag: x.d.flags.__setitem__(f_, True)).until(600)
    check(f"{label}: one press, refused, FAILED at once with the firmware's reason, alerted, switch off",
          len(r.d.presses) == 1 and needle in r.last() and r.last().startswith("FAILED TO START")
          and len(r.created()) >= 1 and not r.arm_left_on() and r.d.attempts == 0, f"{r.gate()} {r.last()[:90]}")

# ======================================================================================================================
print("\n[6] a start transaction that began and failed is never retried")
# ======================================================================================================================
for outcome, needle in (("write_failed", "ACTIVATION WRITE FAILED"), ("capture_failed", "could not capture")):
    r = Run(outcome=outcome).until(600)
    check(f"{outcome}: exactly one press passes the gate, none after; FAILED (transaction began; not retried); alerted",
          sum(1 for _, o in r.d.presses if o == "PASSED") == 1 and len(r.d.presses) == 1 and needle in r.last()
          and "not retried" in r.last() and len(r.created()) == 1, f"{r.gate()} {r.last()}")

# ======================================================================================================================
print("\n[7] the authorised window")
# ======================================================================================================================
r = Run(phase=0.0, delays=(0.05,)).until(7300)
check("an on-time start keeps the full requested duration (120 min) - no regression", r.d.duration == 120)
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 400))).until(7300)
check("a start delayed ~7 min is clamped (113 min) and ends no later than 30 s after 13:00",
      r.d.successes == 1 and r.d.duration < 120 and r.d.ends_at <= r.end_ts + 30,
      f"{r.d.duration} {S.local_str(r.d.ends_at)}")
for dur in (1, 2, 5):
    r = Run(duration=dur).until(dur * 60 + 120)
    check(f"a {dur}-minute window still starts and ends within 30 s of its end", r.d.successes == 1
          and r.d.ends_at <= r.end_ts + 30, f"{r.last()} {r.d.ends_at and S.local_str(r.d.ends_at)}")
r = Run(duration=5, setup=lambda x: x.d.rtc.append((ST - 5, ST + 3600))).until(900)
check("a short window that never clears: no press in its last 30 s, FAILED, alerted",
      r.presses() and max(r.presses()) < 5 * 60 - 30 and r.last().startswith("FAILED") and r.created(), str(r.presses()[-1:]))

# ======================================================================================================================
print("\n[8] the watchdog")
# ======================================================================================================================
r = Run(lose={"start"}).until(7300)
check("a lost start trigger is caught at +3 min: alert 'missed', started for the rest of the window",
      r.d.successes == 1 and 180 <= r.d.started_at - ST <= 240 and any("missed" in n[3] for n in r.created())
      and r.d.ends_at <= r.end_ts + 30, f"{r.d.started_at - ST:.0f} {r.created()}")
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 300))).until(7300)
check("a start still retrying at +3 min is not 'missed' (no watchdog alert, one script run)",
      r.d.successes == 1 and r.created() == [] and len(r.ha.runs) == 1, f"{r.created()} {r.ha.runs}")
r = Run(lose={"start", "watchdog"}).until(7300)
check("control: with the watchdog also lost nothing starts (the watchdog is what recovers)", r.d.successes == 0)

# ======================================================================================================================
print("\n[9] readiness, 5 minutes before")
# ======================================================================================================================
r = Run(setup=lambda x: x.d.set_offline(ST - 400, ST - 100)).until(-200)
check("the dongle offline at 10:55: 'not ready' alert naming the blocker", any("not ready" in n[3] for n in r.created())
      and "telemetry offline" in r.w.notifications["ecco_free_power_schedule"]["message"])
r.until(7300)
check("...it then starts on time and the alert is cleared", r.d.successes == 1 and "ecco_free_power_schedule" not in r.w.notifications)
r = Run().until(-1)
check("ready at 10:55: no alert", r.created() == [])

# ======================================================================================================================
print("\n[10] Home Assistant restart")
# ======================================================================================================================


def down_then_back(down_from: float, back_at: float, until: float) -> Run:
    """Home Assistant stops at down_from and starts again at back_at; the dongle keeps running throughout."""
    x = Run()
    x.w.run_until(down_from)
    x.ha.stop()
    x.w.run_until(back_at)
    x.ha = S.HA(x.w, yaml.safe_load(PKG_TEXT))
    x.ha.start()
    x.w.run_until(until)
    return x


r = down_then_back(ST - 40, ST - 10, ST + 7300)
check("HA restarted at 10:59:20-10:59:50: starts on time, no alert", r.d.successes == 1 and r.d.started_at - ST < 60
      and r.created() == [], f"{r.created()}")
r = down_then_back(ST - 120, ST + 600, ST + 7300)
check("HA down 10:58-11:10 (the start trigger missed): recovered after the restart with an alert, ends inside the window",
      r.d.successes == 1 and 600 <= r.d.started_at - ST <= 700 and any("missed" in n[3] for n in r.created())
      and r.d.ends_at <= r.end_ts + 30, f"{r.d.started_at and r.d.started_at - ST} {r.created()}")
r = down_then_back(ST - 120, ST + 7300, ST + 7400)
check("HA back only after the window ended: MISSED recorded, alerted, nothing pressed, status FAILED",
      r.last().startswith("MISSED") and any("missed" in n[3] for n in r.created()) and r.d.press_log == []
      and r.status() == "FAILED", f"{r.last()} {r.created()}")

# ======================================================================================================================
print("\n[11] the status sensor")
# ======================================================================================================================
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 30)))
seen = []
r.w.listeners.append(lambda k: seen.append(r.status()) if not seen or seen[-1] != r.status() else None)
r.until(7300)
check("ARMED -> STARTING -> ACTIVE -> COMPLETED", [s_ for s_ in seen if s_ in ("ARMED", "STARTING", "ACTIVE", "COMPLETED")][:4]
      == ["ARMED", "STARTING", "ACTIVE", "COMPLETED"], str(seen[:8]))
r = Run(setup=lambda x: x.d.flags.__setitem__("snapshot", True)).until(600)
check("a failed schedule shows FAILED until re-armed", r.status() == "FAILED")
r.w.set(ARMED, "on")
check("...re-arming shows ARMED", r.status() == "ARMED")

# ======================================================================================================================
print("\n[12] mutation")
# ======================================================================================================================


def down_then_back_text(text: str, down_from: float, back_at: float, until: float, setup=None) -> Run:
    x = Run(text, setup=setup)
    x.w.run_until(down_from)
    x.ha.stop()
    x.w.run_until(back_at)
    x.ha = S.HA(x.w, yaml.safe_load(text))
    x.ha.start()
    x.w.run_until(until)
    return x


def battery(text: str) -> dict:
    res = {}
    try:
        worst = 0
        ok = True
        for p in range(0, 600, 5):
            for dl in ((0.05,), INCIDENT_DELAYS):
                x = Run(text, phase=p / 10, delays=dl).until(720)
                ok = ok and x.d.active
                worst = max(worst, len(x.d.presses))
        res["phase"] = ok and worst <= 6
        x = Run(text, setup=lambda y: y.d.rtc.append((ST - 5, ST + 60))).until(600)
        res["retry"] = x.d.successes == 1
        x = Run(text, setup=lambda y: y.d.flags.__setitem__("snapshot", True)).until(600)
        res["persistent"] = len(x.d.presses) == 1 and x.created() != []
        x = Run(text, outcome="capture_failed").until(600)
        res["transaction"] = len(x.d.presses) == 1 and x.created() != []
        x = Run(text, setup=lambda y: y.d.rtc.append((ST - 5, ST + 3600))).until(1200)
        res["deadline"] = max(x.presses()) <= 600 and x.created() != []
        x = Run(text, setup=lambda y: y.d.rtc.append((ST - 5, ST + 400))).until(7300)
        res["clamp"] = x.d.ends_at is not None and x.d.ends_at <= x.end_ts + 30
        x = Run(text, lose={"start"}).until(7300)
        res["watchdog"] = x.d.successes == 1
        x = down_then_back_text(text, ST - 120, ST + 60, ST + 900, setup=lambda y: y.d.rtc.append((ST - 5, ST + 420)))
        res["no_double"] = x.d.successes == 1 and not any("already running" in m for m in x.w.warnings)
        x = Run(text, setup=lambda y: y.d.set_offline(ST - 60, ST + 180)).until(600)
        res["offline"] = x.d.successes == 1 and all(not (ST - 60 <= ST + p < ST + 180) for p in x.presses())
    except Exception as exc:  # noqa: BLE001 - a mutant that breaks the scripts is caught too
        res["crash"] = f"{type(exc).__name__}: {exc}"
    return res


base = battery(PKG_TEXT)
check("the mutation battery holds on the real package", all(v is True for v in base.values()), str(base))
MUTANTS = [
    ("one retry only (the pre-fix policy)", "max_attempts: 60", "max_attempts: 2", "retry"),
    ("spacing locked to the 10 s poll (6.85 s + the ~3.15 s press overhead = one 10 s cycle per attempt)",
     "seconds: \"{{ (2.3 if repeat.index <= 8 else 12.6) + 1.7 * (repeat.index % 4) }}\"", "seconds: 6.85", "phase"),
    ("persistent refusals retried too", "s.startswith('REJECTED - Modbus bus busy with another transaction')",
     "s.startswith('REJECTED')", "persistent"),
    ("a begun transaction retried",
     "                                  FAILED TO START - {{ states('sensor.ecco_clock_dongle_free_power_status') }}\n"
     "                                  (start transaction began on attempt {{ repeat.index }}; not retried)\n",
     "                                  STARTING - retry after a begun transaction\n", "transaction"),
    ("no start deadline", "as_timestamp(now()) + 600", "as_timestamp(now()) + 99999", "deadline"),
    ("no duration clamp", "(((window_end | float(0)) - as_timestamp(now()) + 20) / 60) | round(0, 'floor') | int(0)] | min }}",
     "99999] | min }}", "clamp"),
    ("no watchdog", "and as_timestamp(now()) - s >= 180 }}", "and false }}", "watchdog"),
    ("the start branch as the default (a watchdog tick during a restart recovery calls the script again)",
     "          # Only the start trigger starts on time; a readiness or watchdog tick never falls through to here.\n"
     "          - conditions:\n              - condition: trigger\n                id: start\n            sequence:\n",
     "        default:\n", "no_double"),
    ("pressing while the dongle is offline",
     "                    # The dongle is offline: press nothing, wait and look again (bounded by retry_until).\n"
     "                    - conditions:\n",
     "                    # The dongle is offline: press nothing, wait and look again (bounded by retry_until).\n"
     "                    - conditions:\n                        - condition: template\n"
     "                          value_template: \"{{ false }}\"\n", "offline"),
]
for name, anchor, repl, key in MUTANTS:
    cnt = PKG_TEXT.count(anchor)
    if cnt != 1:
        check(f"mutant '{name}': its anchor occurs exactly once", False, f"{cnt}x: {anchor[:70]!r}")
        continue
    res = battery(PKG_TEXT.replace(anchor, repl))
    check(f"mutant '{name}' is caught by '{key}'", res.get(key) is not True or "crash" in res, str(res))
for name, anchor, repl in (("equivalent: the attempt cap written as 59 + 1", "max_attempts: 60", "max_attempts: \"{{ 59 + 1 }}\""),):
    res = battery(PKG_TEXT.replace(anchor, repl))
    check(f"control '{name}' survives the battery", all(v is True for v in res.values()), str(res))

# ======================================================================================================================
print("\n[13] the post-export declaration (PEX entry fps1)")
# ======================================================================================================================
import _fps1_scope as F  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite pins fps1's declaration)

FPS1_FINGERPRINT = "dfc6e5acbfb684f9407021d22d336f3d1e09bdbbae6a6cc3c165090c53f8300d"
FE1_FINGERPRINT = "211221b095bcdb61b2e7a2cfdd38fb28c871319d46d9acaf6e4f315a690de57e"
BEFORE_SHA = "0caa6714bef18946"   # the package as of fe1 (sha256 prefix, LF)
FPS1 = sc.CHAIN.entry("fps1")
ids = [e.id for e in sc.POST_EXPORT_ENTRIES]
check("fps1 is the tenth post-export entry, appended right after fe1", ids.index("fps1") == 9 and sc.CHAIN.prev_id("fps1") == "fe1",
      str(ids))
check("fps1 declares exactly the schedule package as frozen (reverter + checkpoint), nothing chain-pinned, and no delta, op path, "
      "include, substitution, banned token or tag",
      set(FPS1.frozen_reverts) == set(FPS1.frozen_checkpoints) == {PKG_REL} == set(F.FROZEN_REVERTERS)
      and not FPS1.reverts and not FPS1.checkpoints and not F.PINNED_REVERTERS
      and not FPS1.deltas and not FPS1.op_paths_changed and not FPS1.includes_added and not FPS1.subst_added
      and not FPS1.subst_changed and not FPS1.subst_removed and not FPS1.banned_fw_added and not FPS1.banned_files
      and not FPS1.tags_declared and not FPS1.tags_promoted)
check("fps1 declares the four files it adds (the incident record, the simulator, this suite, its scope module) and each exists",
      FPS1.added_files == F.ADDED_FILES and len(F.ADDED_FILES) == 4 and all((ROOT / f).is_file() for f in FPS1.added_files))
check("ENROLLED stays at six files and the package is a pub0-frozen file", len(_pex.ENROLLED) == 6 and PKG_REL in _pex.FROZEN)
check("fps1's fingerprint is the pinned value, linked to fe1's",
      FPS1.fingerprint == FPS1_FINGERPRINT == _pex.fingerprint(FPS1) and _pex.record(FPS1)["parent"] == FE1_FINGERPRINT)   # PEX: hash link
check("undone exactly, the package is its fe1 state byte for byte, the pre-fix policy (one retry after 12 s, no alert)",
      F.sha(OLD_TEXT).startswith(BEFORE_SHA) and 'delay: "00:00:12"' in OLD_TEXT and "persistent_notification" not in OLD_TEXT)
check("the fps1 pair round-trips (applying it to the fe1 text gives the live package)", F.add_fps1_package(OLD_TEXT) == PKG_TEXT)

# ======================================================================================================================
print("")
if FAILS:
    print(f"{len(FAILS)} FAILED, {PASSES} passed")
    sys.exit(1)
print(f"All {PASSES} scheduled Free Power reliability checks passed.")
print("These prove the package's control flow against a model of the dongle offline; they prove nothing about a live Home "
      "Assistant, the dongle or the inverter.")
