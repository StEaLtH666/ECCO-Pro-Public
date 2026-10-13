"""Offline reliability suite for Scheduled Dump to Grid (post-export entry dgs1; the review that followed the 11 Oct 2026
scheduled Free Power incident, fps1).

The Dump to Grid start gate (firmware script start_dump_to_grid_override) is the same shape as Free Power's: one condition, and
a refusal branch that publishes one REJECTED text and turns the write enable off with no other side effect. Its last test is the
Modbus bus: it refuses while any frame is queued or awaiting its reply. The package pressed at about +2 s and retried once at about
+35 s (the timing fps1 proved locked to the 10 s telemetry poll), retried on ANY non-start (also after a start transaction had
begun), raised no alert, had no missed-trigger watchdog, and BLOCKED for good when the dongle read "off" at the start instant.

The REAL package YAML (and, for the reproduction, the package as of fps1, undone exactly by the PEX layer) runs under the FPS1
interpreter (_ha_script_sim.py) with a model of the Dump to Grid gate, transaction and timer (_ha_dump_sim.py), using the
Modbus busy windows measured on 11 Oct and the start latency measured on the real 6 Oct scheduled Dump start.

  [0] static        package shape unchanged (helpers, cancel script, arm validation, status attributes), entity ids exist in
                    the firmware, the model's refusal texts are the firmware's own in its own order, the retried refusals are
                    exactly the transient ones, only safe services
  [1] defects       the package as of fps1: both presses refused by the bus (nothing written, FAILED, no alert); a second
                    start transaction after one that began and failed; the real failure hidden behind a later refusal; the
                    write enable left ON by a press the firmware dropped (then a stray press starts an unplanned session);
                    the dongle offline at the start instant (aborted run, schedule left armed, no alert)
  [2] fix           the same inputs now start, verified ACTIVE, inside the authorised window
  [3] every phase   the poll phase swept over a whole minute x press-handling delays: old vs new; never two transactions
  [4] transient     RTC correction, NTP, offline, SOC / configuration / grid CT staleness, a press that never arrived
  [5] persistent    snapshot pending, Free Power owns, recovery blocked, reg 244, polling off, TOU slot, SOC at the floor
  [6] transaction   a start that passed the gate and then failed is never retried, and alerts
  [7] window        duration clamp, the start deadline, short windows
  [8] watchdog      a lost start trigger is recovered at +3 min with an alert
  [9] readiness     5 min before: an alert naming each blocker; silent when ready
  [10] restart      Home Assistant restart inside / after the window
  [11] status       ARMED -> STARTING -> ACTIVE -> COMPLETED, and FAILED
  [12] review       cancel mid-retry, a stalled view, the owner's own START racing the schedule, a slow transaction, service
                    errors, staging never confirmed, the longest firmware text, a Free Power transaction at the start
  [13] mutation     in-memory mutants of the package are each caught; an equivalent rewrite survives
  [14] PEX          the dgs1 declaration

Writes nothing; no Home Assistant, no network, no hardware. It proves the package's control flow against a model of the dongle
offline; it proves nothing about a live Home Assistant, the dongle or the inverter.
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

PKG_REL = "home-assistant/packages/ecco_dump_to_grid_schedule.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
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


START = "2026-10-11 18:00:00"
ST = S.parse_local(START)
LAST = "input_text.ecco_dump_to_grid_schedule_last_result"
ARMED = "input_boolean.ecco_dump_to_grid_schedule_armed"
STATUS = "sensor.ecco_dump_to_grid_schedule_status"
SCRIPT = "script.ecco_dump_to_grid_start_scheduled"
DELAYS_6OCT = (0.117,)          # measured on 6 Oct: the gate answered 0.117 s after Home Assistant pressed


class Run:
    """One simulated schedule: Home Assistant + the package + the dongle, armed at 17:51 for START."""

    def __init__(self, text=PKG_TEXT, phase=0.0, delays=DELAYS_6OCT, start=START, duration=60, power=3000, stop_soc=40,
                 setup=None, arm=True, lose=(), outcome="ok", transaction_s=4.07, offline_raises=True):
        self.w = S.World(S.parse_local("2026-10-11 17:50:00"))
        D.add_ha_filters(self.w)
        self.ha = S.HA(self.w, yaml.safe_load(text))
        self.d = D.DumpDongle(self.w, phase=phase, handle_delays=delays, outcome=outcome, transaction_s=transaction_s,
                              offline_raises=offline_raises)
        w = self.w
        w.set("input_datetime.ecco_dump_to_grid_schedule_start", start)
        w.set("input_number.ecco_dump_to_grid_schedule_duration", f"{float(duration)}")
        w.set("input_number.ecco_dump_to_grid_schedule_power", f"{float(power)}")
        w.set("input_number.ecco_dump_to_grid_schedule_stop_soc", f"{float(stop_soc)}")
        w.set(ARMED, "off")
        w.set(LAST, "")
        w.set("input_boolean.ecco_free_power_schedule_armed", "off")
        self.start_ts = S.parse_local(start)
        self.end_ts = self.start_ts + duration * 60
        self.ha.start()
        for a in self.ha.automations:
            a.disabled_triggers |= set(lose)
        if setup:
            setup(self)
        w.run_until(S.parse_local("2026-10-11 17:51:00"))
        if arm:
            w.set(ARMED, "on")

    def until(self, seconds_after_start: float) -> "Run":
        self.w.run_until(self.start_ts + seconds_after_start)
        return self

    def gate(self):
        return [(round(t - self.start_ts, 3), o) for t, o in self.d.presses]

    def passed(self):
        return sum(1 for _, o in self.d.presses if o == "PASSED")

    def presses(self):
        return [t - self.start_ts for t in self.d.press_log]

    def created(self):
        return [n for n in self.w.notification_log if n[1] == "create"]

    def last(self):
        return self.w.state(LAST)

    def status(self):
        return self.w.state(STATUS)

    def arm_left_on(self):
        return self.w.state(D.D_ARM) == "on"


def old_package_text() -> str:
    import _pex  # noqa: E402  (PEX: the package as of fps1 - dgs1 undone exactly, sha256-checked at each step)
    return _pex.as_of(PKG_REL, "fps1", _pex.read(PKG_REL))   # PEX: the pre-dgs1 package for the reproduction


OLD_TEXT = old_package_text()

# ======================================================================================================================
print("[0] static")
# ======================================================================================================================
pkg = yaml.safe_load(PKG_TEXT)
old = yaml.safe_load(OLD_TEXT)
shape = {k: len(v) for k, v in pkg.items()}
check("the package keeps its helper, script and automation counts (1/1/3/1 helpers, 2 scripts, 3 automations, 1 template)",
      shape == {k: len(v) for k, v in old.items()} == {"input_boolean": 1, "input_datetime": 1, "input_number": 3,
                                                         "input_text": 1, "script": 2, "automation": 3, "template": 1},
      str(shape))
check("helper definitions, the cancel script and the template sensor's attributes are unchanged",
      all(pkg[k] == old[k] for k in ("input_boolean", "input_datetime", "input_number", "input_text"))
      and pkg["script"]["ecco_dump_to_grid_cancel_schedule"] == old["script"]["ecco_dump_to_grid_cancel_schedule"]
      and pkg["template"][0]["sensor"][0]["attributes"] == old["template"][0]["sensor"][0]["attributes"])
new_av, old_av = (next(a for a in p["automation"] if a["id"] == "ecco_dump_to_grid_schedule_arm_validation") for p in (pkg, old))
check("the arm validation is unchanged except that a successful arm also clears the two schedule alerts",
      {k: v for k, v in new_av.items() if k != "actions"} == {k: v for k, v in old_av.items() if k != "actions"}
      and new_av["actions"][0] == old_av["actions"][0]
      and new_av["actions"][1]["choose"] == old_av["actions"][1]["choose"]
      and new_av["actions"][1]["default"][0] == old_av["actions"][1]["default"][0]
      and [a["data"]["notification_id"] for a in new_av["actions"][1]["default"][1:]]
      == ["ecco_dump_to_grid_schedule", "ecco_dump_to_grid_schedule_readiness"])
fw_names = set(re.findall(r'name: "([^"]+)"', FW_TEXT))
fw_slugs = {re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_") for n in fw_names}   # Home Assistant's slugify
used = set(re.findall(r"\b(?:binary_sensor|sensor|switch|button|number)\.ecco_clock_dongle_([a-z0-9_]+)", PKG_TEXT))
built = {f"ecco_timezone{i}_{k}" for i in range(1, 7) for k in ("time", "charge")}   # the arm validation's assembled slot ids
check(f"every dongle entity the package uses exists in the firmware ({len(used)} ids, plus the 12 assembled TOU slot ids)",
      used - {"ecco_timezone"} <= fw_slugs and built <= fw_slugs and "ecco_timezone" in used,
      str(sorted((used - {"ecco_timezone"} | built) - fw_slugs)))
gate_else = FW_TEXT[FW_TEXT.index("bool armed = id(dump_write_enable).state;"):]
gate_else = gate_else[:gate_else.index("id(dump_write_enable).turn_off();")]
subst = dict(re.findall(r"^  (ecco_[a-z0-9_]+): \"([^\"]*)\"", FW_TEXT, re.M))
fw_rejects = [re.sub(r"\$\{(\w+)\}", lambda m: subst[m.group(1)], r)
              for r in re.findall(r'publish_state\("(REJECTED - [^"]+)"\)', gate_else)]
fw_slot = re.findall(r'snprintf\(msg, sizeof\(msg\), "(REJECTED - lease window overlaps TOU slot %d[^"]+)"', gate_else)
model = [v for k, v in D.REJECT.items() if k != "tou_slot"]
check(f"the model's {len(D.REJECT)} refusal texts are the firmware gate's own texts, in the firmware's own order (the generic "
      "last-resort text needs no model: no modelled condition reaches it)",
      model == fw_rejects[:-1] and fw_rejects[-1] == "REJECTED - Dump to Grid safety precondition failed" and len(fw_slot) == 1 and fw_slot[0].replace("%d", "{slot}") == D.REJECT["tou_slot"]
      and list(D.REJECT)[-1] == "bus", f"{model}\n{fw_rejects}")
retried = re.findall(r"s\.startswith\('(REJECTED - [^']+)'\)", PKG_TEXT)
TRANSIENT = ("Modbus bus busy", "RTC correction currently active", "another inverter write is active",
             "inverter configuration offline", "valid NTP time required", "plausible live battery voltage required",
             "plausible live battery SOC required", "battery SOC telemetry is stale", "no fresh inverter configuration readback",
             "grid CT telemetry is not fresh", "arm Dump to Grid Write Enable first")
all_fw = fw_rejects + [fw_slot[0]]
check(f"the {len(retried)} retried refusals are verbatim prefixes of the firmware gate's texts, exactly the transient ones",
      len(retried) == len(TRANSIENT) == 11 and all(any(r.startswith(p) for r in fw_rejects) for p in retried)
      and all(any(t in p for p in retried) for t in TRANSIENT), f"{retried}")
persistent = [r for r in all_fw if not any(r.startswith(p) for p in retried)]
check(f"...and the {len(persistent)} other refusals (recovery blocked, already active, snapshot pending, Free Power owns, reg 244, "
      "polling off, TOU unreadable / slot, SOC at the floor, the three ranges, generic) are never retried",
      len(persistent) == 13 and len(persistent) + len(retried) == len(all_fw), str(persistent))
services = set(re.findall(r"action: ([a-z_]+\.[a-z_]+)", PKG_TEXT))
check("the package calls only helper, dongle-control, script and notification services (no register or Modbus path)",
      services <= {"input_text.set_value", "input_boolean.turn_off", "number.set_value", "switch.turn_on", "switch.turn_off",
                   "button.press", "script.ecco_dump_to_grid_start_scheduled", "persistent_notification.create",
                   "persistent_notification.dismiss"}, str(sorted(services)))
check("the package never calls an ESPHome action, a Modbus service or a register write, and never a recovery button",
      not any(re.search(r"esphome|modbus|register", sv, re.I) for sv in services)
      and "force_restore" + "_original" not in PKG_TEXT and "accept" + "_current_state" not in PKG_TEXT)
check("the only dongle controls touched are the three staging numbers, the write enable and the START button (as before)",
      set(re.findall(r"(?:number|switch|button)\.ecco_clock_dongle_\w+", PKG_TEXT))
      == set(re.findall(r"(?:number|switch|button)\.ecco_clock_dongle_\w+", OLD_TEXT)) == {D.D_DUR, D.D_PWR, D.D_SOC, D.D_ARM,
                                                                                               D.D_PRESS})

# ======================================================================================================================
print("\n[1] the defects, reproduced with the package as of fps1")
# ======================================================================================================================


def find_phase(text, pred, delays=DELAYS_6OCT):
    for i in range(0, 600, 5):
        r = Run(text, phase=i / 10, delays=delays).until(180)
        if pred(r):
            return i / 10, r
    return None, None


ph, r = find_phase(OLD_TEXT, lambda x: len(x.d.presses) == 2 and all("bus busy" in o for _, o in x.d.presses))
check("D1 a poll phase exists where the old package's two presses (+2.1 s, +35.1 s) both land in a telemetry read",
      r is not None and [round(t) for t, _ in r.gate()] == [2, 35], str(r and r.gate()))
if r:
    check("...nothing is written (no start transaction began)", r.d.attempts == 0 and not r.d.active)
    check("...the result is FAILED TO START - REJECTED - Modbus bus busy, the schedule disarms, status IDLE",
          r.last().startswith("FAILED TO START - REJECTED - Modbus bus busy") and r.w.state(ARMED) == "off"
          and r.status() == "IDLE", f"{r.last()} / {r.status()}")
    check("...and no alert of any kind is raised", r.created() == [])
    r2 = Run(phase=ph).until(7300)
    check(f"...the new package at the same phase ({ph} s) starts", r2.d.successes == 1 and r2.last().startswith("STARTED OK"),
          r2.last())
r = Run(OLD_TEXT, phase=1.0, outcome="capture_failed").until(180)
check("D2 a start transaction that began and failed with nothing written is pressed AGAIN by the old package: a second start "
      "transaction (a second snapshot capture) runs", r.passed() == 2 and r.d.attempts == 2, str(r.gate()))
r = Run(OLD_TEXT, phase=1.0, outcome="verify_failed").until(180)
check("D3 after a transaction that failed with its snapshot retained, the old retry is refused ('snapshot pending') and the "
      "recorded result names that refusal, not the real failure; no alert",
      r.passed() == 1 and "saved snapshot pending" in r.last() and "verify mismatch" not in r.last() and r.created() == [],
      f"{r.gate()} {r.last()}")
r = Run(OLD_TEXT, transaction_s=40.0).until(180)
check("D4 (theoretical: the measured transaction is ~4 s) a transaction still running at +35 s: the old retry re-arms, the "
      "firmware's single-mode start script drops the press, and the write enable is LEFT ON while Dump runs",
      r.passed() == 1 and r.d.dropped == 1 and r.d.active and r.arm_left_on() and r.last().startswith("STARTED OK ON RETRY"),
      f"{r.gate()} {r.last()} {r.w.state(D.D_ARM)}")
r.until(3711)                                   # an instant clear of the poll (a busy bus would refuse the stray press)
r.d.press_log.append(r.w.t)
r.d._gate()                                     # a stray press of START after the session ended (no arm step by anyone)
r.until(3760)                                   # this model's transaction takes 40 s
check("...and it stays on after the session ends: one stray START press then begins an UNPLANNED Dump session (arm bypassed)",
      r.passed() == 2 and r.d.active, str(r.gate()))
r = Run(OLD_TEXT, setup=lambda x: x.d.set_offline(ST - 60, ST + 120)).until(600)
check("D5 the dongle offline at the start instant (HA shows 'unavailable', not 'off'): the old run stages into an unavailable "
      "dongle, Home Assistant raises, the run aborts - the schedule stays ARMED with 'STARTING', nothing starts, no alert",
      r.d.successes == 0 and r.w.state(ARMED) == "on" and r.last().startswith("STARTING") and r.created() == []
      and any("aborted" in m for m in r.w.warnings), f"{r.last()} {r.w.warnings[:2]}")
r = Run(OLD_TEXT, setup=lambda x: x.w.at(ST - 1, lambda: x.w.set(S.E_TEL, "off")))
r.w.at(ST + 20, lambda: r.w.set(S.E_TEL, "on"))
r.until(600)
check("D6 telemetry reading 'off' for a moment at the start instant: the old package BLOCKs for good (no wait, no retry, no alert)",
      r.d.press_log == [] and r.last().startswith("BLOCKED") and r.created() == [], r.last())
r = Run(OLD_TEXT, lose={"0"}).until(900)
check("D7 a lost start trigger: the old package has no watchdog - nothing starts and nobody is told",
      r.d.press_log == [] and r.created() == [] and r.w.state(ARMED) == "on", f"{r.last()} {r.w.state(ARMED)}")

# ======================================================================================================================
print("\n[2] the fix, same inputs")
# ======================================================================================================================
r = Run().until(3700)
check("the new package starts: ACTIVE verified, STARTED OK recorded, the schedule disarmed",
      r.d.successes == 1 and r.last().startswith("STARTED OK") and r.w.state(ARMED) == "off", r.last())
check("...within 40 s of the start time", r.d.started_at - r.start_ts <= 40, str(r.d.started_at - r.start_ts))
check("...with exactly the requested power, Stop SOC and duration at the gate", r.d.gate_values == (3000, 40, 60),
      str(r.d.gate_values))
check("...the session ends within 30 s of the authorised window's end", r.d.ends_at <= r.end_ts + 30, S.local_str(r.d.ends_at))
check("...no alert when it starts, the write enable ends off, status COMPLETED after the session",
      r.created() == [] and not r.arm_left_on() and r.status() == "COMPLETED", r.status())

# ======================================================================================================================
print("\n[3] every poll phase")
# ======================================================================================================================
stats = {}
for name, text in (("old", OLD_TEXT), ("new", PKG_TEXT)):
    n = fails = worst_presses = doubles = 0
    worst_start = 0.0
    for i in range(0, 600, 5):                          # the whole minute, 0.5 s steps
        for dl in ((0.05,), DELAYS_6OCT, (0.6, 0.1)):
            r = Run(text, phase=i / 10, delays=dl).until(720)
            n += 1
            doubles += r.passed() > 1
            if not r.d.active or r.arm_left_on():
                fails += 1
                continue
            worst_presses = max(worst_presses, len(r.d.presses))
            worst_start = max(worst_start, r.d.started_at - r.start_ts)
    stats[name] = (n, fails, worst_presses, worst_start, doubles)
n, f, wp, ws, dbl = stats["old"]
check(f"the old package fails at {f / n:.1%} of poll phases x press delays ({n} runs; the fps1 incident's ~1-in-20 risk)",
      0.02 <= f / n <= 0.12, str(stats["old"]))
n, f, wp, ws, dbl = stats["new"]
check(f"the new package starts at EVERY phase and press delay ({n} runs): at most {wp} presses, started by +{ws:.0f} s",
      f == 0 and wp <= 6 and ws <= 60, str(stats["new"]))
check("...and never runs two start transactions (old or new, every run)", stats["old"][4] == 0 and dbl == 0, str(stats))

# ======================================================================================================================
print("\n[4] transient refusals: retried, bounded")
# ======================================================================================================================
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 49))).until(600)
check("an RTC correction running at the start (49 s) is waited out: refused as RTC, then started",
      r.d.successes == 1 and any("RTC correction" in o for _, o in r.gate()) and r.d.started_at - ST < 70, str(r.gate()))
r = Run(setup=lambda x: x.d.set_offline(ST - 60, ST + 180)).until(600)
check("the dongle offline from 17:59 to 18:03: nothing staged or pressed while offline, started once back, no alert",
      r.d.successes == 1 and all(not (ST - 60 <= ST + p < ST + 180) for p in r.presses()) and r.created() == []
      and not any("aborted" in m for m in r.w.warnings), f"{r.presses()[:3]} {r.w.warnings[:2]}")
for key, label in (("soc_stale", "battery SOC telemetry stale (an RTC pause of the poll)"),
                   ("cfg_stale", "no fresh configuration readback yet"),
                   ("grid_stale", "grid CT telemetry stale")):
    r = Run(setup=lambda x, k=key: getattr(x.d, k).append((ST - 30, ST + 45))).until(600)
    check(f"{label} for the first 45 s: refused with that reason, retried, started",
          r.d.successes == 1 and r.gate()[0][1] == D.REJECT[key] and r.passed() == 1, str(r.gate()[:2]))
r = Run(setup=lambda x: x.d.flags.__setitem__("ntp_bad", True))
r.w.at(ST + 60, lambda: r.d.flags.__setitem__("ntp_bad", False))
r.until(600)
check("no valid NTP time for the first minute: retried, then started", r.d.successes == 1 and any("NTP" in o for _, o in r.gate()))
r = Run()
_orig_press = r.d._press


def _drop_first(entity, data, d=r.d):
    if not d.press_log:
        d.press_log.append(d.w.t)            # the first press reaches nobody (API hiccup): never acknowledged
        return
    _orig_press(entity, data)


r.w.service_handlers["button.press"] = _drop_first
r.until(600)
check("a press that never reaches the dongle: HA disarms, sees the switch go off, finds the gate-pass counter unchanged, then "
      "retries and starts", r.d.successes == 1 and len(r.d.press_log) == 2 and not r.arm_left_on()
      and 45 <= r.presses()[1] - r.presses()[0] <= 75, str(r.presses()))
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 3600))).until(1200)
check("a refusal that never clears: retries stop at the deadline (start + 10 min), FAILED with one alert, write enable off",
      r.d.successes == 0 and max(r.presses()) <= 600 and r.last().startswith("FAILED TO START")
      and [n_[2] for n_ in r.created()] == ["ecco_dump_to_grid_schedule"] and not r.arm_left_on(), r.last()[:90])
spacing = sorted({round(b - a, 1) for a, b in zip(r.presses(), r.presses()[1:])})
check(f"...a bounded number of presses ({len(r.presses())}) with uneven spacing that never matches the 10 s poll ({spacing})",
      len(r.presses()) <= 60 and len(spacing) >= 3 and all(abs(s_ - round(s_ / 10) * 10) > 0.5 for s_ in spacing))

# ======================================================================================================================
print("\n[5] persistent refusals: no retry, alert at once")
# ======================================================================================================================


def _flag(name):
    def f(x):
        x.d.flags[name] = True
        if name == "snapshot":
            x.w.set(D.D_SNAP, "on")
    return f


for label, setup, needle in (
        ("a saved snapshot pending restore", _flag("snapshot"), "saved snapshot"),
        ("Free Power owning the inverter", _flag("fp"), "Free Power override"),
        ("recovery blocked (the firmware's longest refusal text)", _flag("corrupt"), "RECOVERY BLOCKED"),
        ("a register 244 proof transaction", _flag("r244"), "Register 244"),
        ("configuration polling switched off", _flag("polling_off"), "Configuration Polling"),
        ("the window overlapping a charging TOU slot", lambda x: setattr(x.d, "tou_slot", 1), "TOU slot 1"),
        ("the battery already at the Stop SOC", lambda x: setattr(x.d, "soc", 40.0), "at or below the requested Stop SOC")):
    r = Run(setup=setup).until(600)
    check(f"{label}: one press, refused, FAILED at once with the firmware's reason, alerted, switch off, nothing written",
          len(r.d.presses) == 1 and needle in r.last() and r.last().startswith("FAILED TO START") and len(r.created()) >= 1
          and not r.arm_left_on() and r.d.attempts == 0 and not any("invalid value" in m for m in r.w.warnings),
          f"{r.gate()} {r.last()[:120]} {r.w.warnings[:2]}")

# ======================================================================================================================
print("\n[6] a start transaction that began and failed is never retried")
# ======================================================================================================================
for outcome in ("capture_failed", "verify_failed", "commit_failed"):
    r = Run(outcome=outcome).until(600)
    check(f"{outcome}: exactly one press passes the gate, none after; FAILED (began; not retried) with the firmware's text; "
          "alerted; write enable off", r.passed() == 1 and len(r.d.presses) == 1 and "not retried" in r.last()
          and D.OUTCOMES[outcome][0][:40] in r.last() and len(r.created()) == 1 and not r.arm_left_on(),
          f"{r.gate()} {r.last()}")

# ======================================================================================================================
print("\n[7] the authorised window")
# ======================================================================================================================
r = Run(phase=0.0, delays=(0.05,)).until(3700)
check("an on-time start keeps the full requested duration (60 min) - no regression", r.d.gate_values[2] == 60)
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 400))).until(3700)
check("a start delayed ~7 min is clamped (53 min) and ends no later than 30 s after the window end",
      r.d.successes == 1 and r.d.gate_values[2] < 60 and r.d.ends_at <= r.end_ts + 30,
      f"{r.d.gate_values} {S.local_str(r.d.ends_at)}")
for dur in (1, 2, 5):
    r = Run(duration=dur).until(dur * 60 + 120)
    check(f"a {dur}-minute window still starts and ends within 30 s of its end", r.d.successes == 1
          and r.d.ends_at <= r.end_ts + 30, f"{r.last()} {r.d.ends_at and S.local_str(r.d.ends_at)}")
r = Run(duration=5, setup=lambda x: x.d.rtc.append((ST - 5, ST + 3600))).until(900)
check("a short window that never clears: no press in its last 30 s, FAILED, alerted",
      r.presses() and max(r.presses()) < 5 * 60 - 30 and r.last().startswith("FAILED") and r.created(), str(r.presses()[-1:]))
r = Run(OLD_TEXT, phase=1.0, setup=lambda x: x.d.rtc.append((ST - 5, ST + 30))).until(3800)
check("control: the old package's late retry (+35 s) ran its full duration past the window end",
      r.d.successes == 1 and r.d.ends_at > r.end_ts + 30, S.local_str(r.d.ends_at or 0))

# ======================================================================================================================
print("\n[8] the watchdog")
# ======================================================================================================================
r = Run(lose={"start"}).until(3700)
check("a lost start trigger is caught at +3 min: alert 'missed', started for the rest of the window",
      r.d.successes == 1 and 180 <= r.d.started_at - ST <= 240 and any("missed" in n_[3] for n_ in r.created())
      and r.d.ends_at <= r.end_ts + 30, f"{r.d.started_at and r.d.started_at - ST} {r.created()}")
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 300))).until(3700)
check("a start still retrying at +3 min is not 'missed' (no watchdog alert, one script run)",
      r.d.successes == 1 and r.created() == [] and len(r.ha.runs) == 1, f"{r.created()} {r.ha.runs}")

# ======================================================================================================================
print("\n[9] readiness, 5 minutes before")
# ======================================================================================================================
r = Run(setup=lambda x: x.d.set_offline(ST - 400, ST - 100)).until(-200)
check("the dongle offline at 17:55: 'not ready' alert naming the blocker", any("not ready" in n_[3] for n_ in r.created())
      and "telemetry offline" in r.w.notifications["ecco_dump_to_grid_schedule_readiness"]["message"])
r.until(3700)
check("...it then starts on time and the alert is cleared", r.d.successes == 1 and not r.w.notifications)
r = Run(setup=lambda x: (setattr(x.d, "soc", 35.0), x.w.set(D.D_BATT, "35.0"))).until(-200)
check("the battery below the Stop SOC 5 min before: the readiness alert names it with both numbers",
      "battery SOC 35% is at or below the Stop SOC 40%" in r.w.notifications.get("ecco_dump_to_grid_schedule_readiness",
                                                                                  {}).get("message", ""))
r = Run().until(-1)
check("ready at 17:55: no alert", r.created() == [])

# ======================================================================================================================
print("\n[10] Home Assistant restart")
# ======================================================================================================================


def down_then_back(text, down_from: float, back_at: float, until: float, setup=None) -> Run:
    x = Run(text, setup=setup)
    x.w.run_until(down_from)
    x.ha.stop()
    x.w.run_until(back_at)
    x.ha = S.HA(x.w, yaml.safe_load(text))
    x.ha.start()
    x.w.run_until(until)
    return x


r = down_then_back(PKG_TEXT, ST - 40, ST - 10, ST + 3700)
check("HA restarted at 17:59:20-17:59:50: starts on time, no alert", r.d.successes == 1 and r.d.started_at - ST < 60
      and r.created() == [])
r = down_then_back(PKG_TEXT, ST - 120, ST + 600, ST + 3700)
check("HA down 17:58-18:10 (the start trigger missed): recovered after the restart with an alert, ends inside the window",
      r.d.successes == 1 and 600 <= r.d.started_at - ST <= 700 and any("missed" in n_[3] for n_ in r.created())
      and r.d.ends_at <= r.end_ts + 30, f"{r.d.started_at and r.d.started_at - ST} {r.created()}")
r = down_then_back(PKG_TEXT, ST - 120, ST + 3700, ST + 3800)
check("HA back only after the window ended: MISSED recorded, alerted, nothing pressed, status FAILED",
      r.last().startswith("MISSED") and any("missed" in n_[3] for n_ in r.created()) and r.d.press_log == []
      and r.status() == "FAILED", f"{r.last()} {r.created()}")

# ======================================================================================================================
print("\n[11] the status sensor")
# ======================================================================================================================
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 30)))
seen = []
r.w.listeners.append(lambda k: seen.append(r.status()) if not seen or seen[-1] != r.status() else None)
r.until(3700)
check("ARMED -> STARTING -> ACTIVE -> COMPLETED",
      [s_ for s_ in seen if s_ in ("ARMED", "STARTING", "ACTIVE", "COMPLETED")][:4] == ["ARMED", "STARTING", "ACTIVE", "COMPLETED"],
      str(seen[:8]))
r = Run(setup=_flag("snapshot")).until(600)
check("a failed schedule shows FAILED until re-armed", r.status() == "FAILED")
r.w.set(ARMED, "on")
check("...re-arming shows ARMED", r.status() == "ARMED")

# ======================================================================================================================
print("\n[12] review: cancel, stale state, races, slow transactions, service errors, long texts")
# ======================================================================================================================


def cancel(x):
    x.ha.start_script("ecco_dump_to_grid_cancel_schedule", {})


for t_cancel in (28.5, 89.0):
    r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 240)))
    r.w.at(ST + t_cancel, lambda x=r: cancel(x))
    r.until(900)
    check(f"the real cancel script at +{t_cancel} s: no press after it, nothing started, CANCELLED, no alert, write enable off",
          r.d.successes == 0 and all(p_ <= t_cancel for p_ in r.presses()) and r.last().startswith("CANCELLED")
          and r.created() == [] and not r.arm_left_on(), f"{[round(p_, 1) for p_ in r.presses()[-3:]]} {r.last()}")
r = Run(setup=lambda x: x.d.rtc.append((ST - 5, ST + 240)))
r.w.at(ST + 89, lambda x=r: cancel(x))


def _rearm(x=r):
    x.w.set("input_datetime.ecco_dump_to_grid_schedule_start", "2026-10-11 19:30:00")
    x.w.set(ARMED, "on")


r.w.at(ST + 95, _rearm)
r.until(400)
check("cancel and re-arm for 19:30: today's run stops (no press after the cancel) and the new schedule stays ARMED, text kept",
      r.d.successes == 0 and all(p_ <= 89 for p_ in r.presses()) and r.w.state(ARMED) == "on" and r.last().startswith("ARMED"),
      f"{r.presses()[-2:]} {r.last()}")
r = Run(phase=5.0, delays=(0.05,))
r.d.stalls.append((ST + 1.0, ST + 45))
r.until(900)
check("Home Assistant's view stalls right after a press that passes: never two transactions; the start is recorded once the "
      "view recovers; the write enable ends off", r.passed() == 1 and r.d.successes == 1 and r.last().startswith("STARTED OK")
      and not r.arm_left_on(), f"{r.gate()} {r.last()}")
r = Run(phase=5.0, delays=(0.05,), outcome="capture_failed")
r.d.stalls.append((ST + 1.0, ST + 45))
r.until(900)
check("...and when that transaction failed: not retried, FAILED, alerted", r.passed() == 1
      and r.last().startswith("FAILED TO START") and r.created() != [], f"{r.gate()} {r.last()}")
for slow in (20.0, 40.0, 70.0):
    r = Run(transaction_s=slow).until(900)
    check(f"a slow start transaction ({slow:.0f} s): waited for, one transaction, STARTED OK, write enable off afterwards",
          r.passed() == 1 and r.d.dropped == 0 and r.d.successes == 1 and r.last().startswith("STARTED OK")
          and not r.arm_left_on(), f"{r.gate()} {r.last()} dropped={r.d.dropped}")
r = Run()
r.d.manual_start(ST - 2)
r.until(600)
op = r.d.op_intervals[0]
check("the owner's own START two seconds before the schedule: nothing staged into that transaction, never pressed during it; "
      "one transaction; Dump active", r.passed() == 1 and not any(op[0] <= t <= op[1] for t, _e, _v in r.d.number_log)
      and r.last().startswith(("STARTED", "BLOCKED")) and not r.arm_left_on(), f"{r.d.number_log} {op} {r.last()}")
r = Run()
r.d.manual_start(ST + 1.0)
r.until(600)
check("the owner pressing START at the same moment: one transaction, the write enable ends off",
      r.passed() == 1 and not r.arm_left_on() and r.d.successes == 1, f"{r.gate()}")
r = Run(setup=lambda x: (x.d.flags.__setitem__("fp_op", True), x.w.set(D.FP_OP, "on")))
r.w.at(ST + 25, lambda: (r.d.flags.__setitem__("fp_op", False), r.w.set(D.FP_OP, "off")))
r.until(600)
check("a Free Power transaction in progress at the start: nothing staged or pressed until it ends, then started",
      r.d.successes == 1 and all(p_ >= 25 for p_ in r.presses()) and r.passed() == 1, str(r.presses()[:2]))
r = Run()
r.w.fail_services["button.press"] = 1
r.until(600)
check("a service error on the press: not aborted, verified as not processed, retried, started",
      r.d.successes == 1 and not any("aborted" in m for m in r.w.warnings), f"{r.last()} {r.w.warnings[:3]}")
r = Run()
r.w.fail_services["switch.turn_on"] = 99
r.until(900)
check("a service error on every arm: nothing pressed, FAILED at the deadline with an alert (never silent)",
      r.d.press_log == [] and r.last().startswith("FAILED") and r.created() != [], f"{r.last()} {r.created()}")
r = Run(setup=lambda x: setattr(x.d, "drop_numbers", True)).until(900)
check("staging that never reaches the dongle: never pressed (it would run with stale values); FAILED at the deadline, alerted",
      r.d.press_log == [] and r.last().startswith("FAILED") and r.created() != [], r.last())
longest = max(len(t) for t in D.REJECT.values()) + 1
r = Run(setup=_flag("corrupt")).until(600)
check(f"the longest firmware refusal ({longest} chars) still fits every result text (<= 255): nothing silently dropped",
      not any("invalid value" in m for m in r.w.warnings) and "RECOVERY BLOCKED" in r.last(), str(r.w.warnings[:2]))
r = Run(setup=lambda x: setattr(x.d, "tou_slot", 3)).until(600)
check("...and the longest assembled one (the TOU slot text) too", not any("invalid value" in m for m in r.w.warnings)
      and "TOU slot 3" in r.last(), r.last())
r = Run(arm=False)
r.w.run_until(ST + 30)
r.w.set(ARMED, "on")
r.until(900)
check("arming with a start time in the past: refused by the arm validation, no 'missed' alert, nothing pressed",
      r.d.press_log == [] and r.created() == [] and r.last().startswith("REJECTED"), f"{r.last()} {r.created()}")
x = Run(arm=False)
x.w.run_until(ST - 600)
x.d._set_arm(True)                                      # left on by a restart between an arm and its press
x.w.run_until(ST - 590)
x.ha.stop()
x.ha = S.HA(x.w, yaml.safe_load(PKG_TEXT))
x.ha.start()
x.w.run_until(ST - 500)
check("Home Assistant restarting with the write enable left on (and nothing armed): startup recovery turns it off",
      not x.arm_left_on() and x.d.press_log == [])

# ======================================================================================================================
print("\n[13] mutation")
# ======================================================================================================================


def battery(text: str) -> dict:
    res = {}
    try:
        ok, worst = True, 0
        for p in range(0, 600, 5):
            for dl in ((0.05,), DELAYS_6OCT):
                y = Run(text, phase=p / 10, delays=dl).until(720)
                ok = ok and y.d.active and y.passed() == 1
                worst = max(worst, len(y.d.presses))
        res["phase"] = ok and worst <= 6
        y = Run(text, setup=lambda z: z.d.rtc.append((ST - 5, ST + 60))).until(600)
        res["retry"] = y.d.successes == 1
        y = Run(text, setup=_flag("fp")).until(600)
        res["persistent"] = len(y.d.presses) == 1 and y.created() != []
        y = Run(text, outcome="capture_failed").until(600)
        res["transaction"] = len(y.d.presses) == 1 and y.created() != []
        y = Run(text, setup=lambda z: z.d.rtc.append((ST - 5, ST + 3600))).until(1200)
        res["deadline"] = max(y.presses()) <= 600 and y.created() != []
        y = Run(text, setup=lambda z: z.d.rtc.append((ST - 5, ST + 400))).until(3700)
        res["clamp"] = y.d.ends_at is not None and y.d.ends_at <= y.end_ts + 30
        y = Run(text, lose={"start"}).until(3700)
        res["watchdog"] = y.d.successes == 1
        y = Run(text, setup=lambda z: z.d.set_offline(ST - 60, ST + 180)).until(600)
        res["offline"] = y.d.successes == 1 and all(not (ST - 60 <= ST + p_ < ST + 180) for p_ in y.presses())
        y = Run(text)
        y.d.manual_start(ST - 2)
        y.until(120)
        o = y.d.op_intervals[0]
        res["race"] = not any(o[0] <= t <= o[1] for t, _e, _v in y.d.number_log)
        y = Run(text, setup=lambda z: (setattr(z.d, "soc", 35.0), z.w.set(D.D_BATT, "35.0"))).until(-200)
        res["readiness"] = "ecco_dump_to_grid_schedule_readiness" in y.w.notifications
        y = Run(text)
        y.until(30)
        res["staged"] = y.d.gate_values == (3000, 40, 60)
    except Exception as exc:  # noqa: BLE001 - a mutant that breaks the scripts is caught too
        res["crash"] = f"{type(exc).__name__}: {exc}"
    return res


base = battery(PKG_TEXT)
check("the mutation battery holds on the real package", all(v is True for v in base.values()), str(base))
MUTANTS = [
    ("one retry only (the pre-fix policy)", "max_attempts: 60", "max_attempts: 2", "retry"),
    ("spacing locked to the 10 s poll", "seconds: \"{{ (2.3 if repeat.index <= 8 else 12.6) + 1.7 * (repeat.index % 4) }}\"",
     "seconds: 6.68", "phase"),
    ("persistent refusals retried too", "s.startswith('REJECTED - Modbus bus busy with another transaction')",
     "s.startswith('REJECTED')", "persistent"),
    ("a begun transaction retried",
     "                                          FAILED TO START - {{ states('sensor.ecco_clock_dongle_dump_to_grid_status')[:120] }}\n"
     "                                          (start transaction began on attempt {{ repeat.index }}; not retried)\n",
     "                                          STARTING - retry after a begun transaction\n", "transaction"),
    ("no start deadline", "as_timestamp(now()) + 600", "as_timestamp(now()) + 99999", "deadline"),
    ("no duration clamp", "(((window_end | float(0)) - as_timestamp(now()) + 20) / 60) | round(0, 'floor') | int(0)] | min }}",
     "99999] | min }}", "clamp"),
    ("no watchdog", "and as_timestamp(now()) - s >= 180\n", "and as_timestamp(now()) - s >= 99999999\n", "watchdog"),
    ("staging while another write is in progress (the not-ready branch disabled)",
     "                    # progress (a transaction that will end by itself). Stage nothing, press nothing; look again.\n"
     "                    - conditions:\n",
     "                    # progress (a transaction that will end by itself). Stage nothing, press nothing; look again.\n"
     "                    - conditions:\n                        - condition: template\n"
     "                          value_template: \"{{ false }}\"\n", "race"),
    ("the Stop SOC not staged", "                        entity_id: number.ecco_clock_dongle_dump_to_grid_stop_soc\n"
     "                      data:\n                        value: \"{{ requested_stop_soc }}\"\n",
     "                        entity_id: number.ecco_clock_dongle_dump_to_grid_stop_soc\n"
     "                      data:\n                        value: \"{{ 25 }}\"\n", "staged"),
    ("no SOC blocker in the readiness check", "{% if soc >= 0 and soc <= floor_ %}", "{% if false %}", "readiness"),
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
print("\n[14] the post-export declaration (PEX entry dgs1)")
# ======================================================================================================================
import _dgs1_scope as G  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite pins dgs1's declaration)

DGS1_FINGERPRINT = "65c52d137893cdde64c8d7a5cd850582093da5a39412a3e2e2d316e82b39bf36"
RSV1_FINGERPRINT = "85808fd4ea7af13a57737a12cdff92ab2cf568eab88a53463dec6e9228b3a590"
BEFORE_SHA = "18610f663df203a0"   # the package as of fps1 (sha256 prefix, LF)
DGS1 = sc.CHAIN.entry("dgs1")
ids = [e.id for e in sc.POST_EXPORT_ENTRIES]
check("dgs1 is the twelfth post-export entry, appended right after rsv1 (which follows fps1)", ids.index("dgs1") == 11
      and sc.CHAIN.prev_id("dgs1") == "rsv1", str(ids))
check("dgs1 declares exactly the schedule package and its frozen package test as frozen (reverter + checkpoint), nothing "
      "chain-pinned, and no delta, op path, include, substitution, banned token or tag",
      set(DGS1.frozen_reverts) == set(DGS1.frozen_checkpoints) == {PKG_REL, G.PKG_TEST_REL} == set(G.FROZEN_REVERTERS)
      and not DGS1.reverts and not DGS1.checkpoints and not G.PINNED_REVERTERS
      and not DGS1.deltas and not DGS1.op_paths_changed and not DGS1.includes_added and not DGS1.subst_added
      and not DGS1.subst_changed and not DGS1.subst_removed and not DGS1.banned_fw_added and not DGS1.banned_files
      and not DGS1.tags_declared and not DGS1.tags_promoted)
check("dgs1 declares the four files it adds (the review record, the Dump model, this suite, its scope module) and each exists",
      DGS1.added_files == G.ADDED_FILES and len(G.ADDED_FILES) == 4 and all((ROOT / f).is_file() for f in DGS1.added_files))
check("ENROLLED stays at six files and both edited files are pub0-frozen files",
      len(_pex.ENROLLED) == 6 and PKG_REL in _pex.FROZEN and G.PKG_TEST_REL in _pex.FROZEN)
check("dgs1's fingerprint is the pinned value, linked to rsv1's",
      DGS1.fingerprint == DGS1_FINGERPRINT == _pex.fingerprint(DGS1) and _pex.record(DGS1)["parent"] == RSV1_FINGERPRINT)   # PEX: hash link
check("undone exactly, the package is its fps1 state byte for byte (press at +2 s, one retry after 12 s, no alert)",
      G.sha(OLD_TEXT).startswith(BEFORE_SHA) and 'delay: "00:00:12"' in OLD_TEXT and "persistent_notification" not in OLD_TEXT)
check("the dgs1 pair round-trips (applying it to the fps1 text gives the live package)", G.add_dgs1_package(OLD_TEXT) == PKG_TEXT)

# ======================================================================================================================
print("")
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed")
    sys.exit(1)
print(f"All {PASSES} scheduled Dump to Grid reliability checks passed.")
print("These prove the package's control flow against a model of the dongle offline; they prove nothing about a live Home "
      "Assistant, the dongle or the inverter.")
