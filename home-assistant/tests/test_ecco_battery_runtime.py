#!/usr/bin/env python3
"""FE-1 battery time-to-reserve (home-assistant/packages/ecco_battery_runtime.yaml): offline proofs of the estimate.

The package's REAL Jinja templates are rendered with stand-ins for the Home Assistant template functions it uses
(states() / states[...] / is_state / state_attr / now / as_timestamp / this / trigger, and HA's forgiving float / int
filters that RAISE without a default), once per simulated minute, in BOTH a plain and an immutable sandboxed Jinja
environment (Home Assistant renders in a sandbox). Model attributes round-trip through ast.literal_eval, as HA parses a
rendered attribute.

  [0] static: read only (template only: no action / service / script / automation / esphome call), the triggers, the two
      entities, every input entity exists (dongle names from the firmware, helpers from ecco_pro.yaml), the device slug only
      inside quoted entity ids (the site renderer's exact rules), no built-in reserve value
  [1] constant discharge: the estimate is exactly (SOC - reserve) x energy-per-percent / power, rounded as documented
  [2] restart and insufficient history: warming up for 10 minutes; a short restart keeps the history, a long one restarts it;
      what was learned survives
  [3] short load spikes (kettle, pump start) are ignored; a sustained step (oven) is followed within the documented time
  [4] variable household load: the estimate stays within the band of a time-weighted reference
  [5] charging, holding (zero / insufficient discharge), solar-assisted discharge
  [6] reserve reached, reserve configuration changes (any value, applied at once; nothing hard-coded), reserve unavailable
  [7] missing and stale telemetry: offline flag, unavailable power, old reports; recovery
  [8] inconsistent SOC: out of range, a jump, zero while discharging
  [9] capacity: the configured value until 3 observations of 5 SOC points each, then the measured energy per percent;
      implausible observations rejected; charging restarts the segment, never the learned value
  [10] boundary and numerical stability: horizon cap, the hold threshold, huge / tiny / garbage values, irregular and backwards
       clocks, a simulated week without drift
  [11] the presentation sensor (what the Energy Flow card reads): lookups only, a model that stops updating is not shown as current
  [12] a second, plain-Python implementation of the documented method agrees with the templates on seeded random traces
  [13] wiring: the manifest deploys the package, the Overview Energy Flow card reads the sensor, the card's status vocabulary
       equals the package's
  [14] mutation: each named mutant of the package is caught by the scenarios above; equivalent rewrites survive
  [15] the post-export declaration (PEX entry fe1): its place after ovw1, exactly the dashboard and VERSION.yaml frozen and the
       manifest chain-pinned, the files it adds, its fingerprint; undone, the three files are their ovw1 state byte for byte

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import ast
import math
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jinja2
import jinja2.sandbox
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PKG_REL = "home-assistant/packages/ecco_battery_runtime.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
FIRMWARE = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
CORE_PKG = (ROOT / "home-assistant" / "packages" / "ecco_pro.yaml").read_text(encoding="utf-8")

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


E_POWER = "sensor.ecco_clock_dongle_ecco_battery_output_power"
E_SOC = "sensor.ecco_clock_dongle_ecco_battery_soc"
E_PV = "sensor.ecco_clock_dongle_ecco_pv_power"
E_ONLINE = "binary_sensor.ecco_clock_dongle_telemetry_online"
E_POLLED = "sensor.ecco_clock_dongle_last_telemetry_update"   # text: the poll time to the second, changes on every good poll
E_RESERVE = "input_number.ecco_minimum_reserve_soc"
E_CAPACITY = "input_number.ecco_battery_model_capacity"
E_MODEL = "sensor.ecco_battery_runtime_model"
E_TTR = "sensor.ecco_battery_time_to_reserve"
INPUTS = (E_POWER, E_SOC, E_PV, E_ONLINE, E_POLLED, E_RESERVE, E_CAPACITY)
STATUSES = {"discharging", "at_reserve", "charging", "holding", "insufficient_data", "stale"}

T0 = datetime(2026, 10, 10, 18, 0, 0, tzinfo=timezone.utc)
_MISSING = object()


# ---------------------------------------------------------------------------------------------------------------------------
# Home Assistant stand-ins
# ---------------------------------------------------------------------------------------------------------------------------
def ha_float(value, default=_MISSING):
    """homeassistant.helpers.template.forgiving_float_filter: a default is required for a non-number."""
    try:
        return float(value)
    except (ValueError, TypeError):
        if default is _MISSING:
            raise ValueError(f"float got invalid input {value!r} and no default") from None
        return default


def ha_int(value, default=_MISSING, base=10):
    """forgiving_int_filter: jinja2's do_int, raising without a default."""
    result = jinja2.filters.do_int(value, default=_MISSING, base=base)
    if result is _MISSING:
        if default is _MISSING:
            raise ValueError(f"int got invalid input {value!r} and no default")
        return default
    return result


def as_timestamp(value, default=_MISSING):
    try:
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        pass
    if default is _MISSING:
        raise ValueError(f"as_timestamp got invalid input {value!r} and no default")
    return default


class StateObj:
    """A Home Assistant State as templates see it. `reported=False` models a core without last_reported."""

    def __init__(self, entity_id, state, last_changed, last_updated, last_reported, attributes, reported=True):
        self.entity_id = entity_id
        self.state = state
        self.last_changed = last_changed
        self.last_updated = last_updated
        if reported:
            self.last_reported = last_reported
        self.attributes = attributes


class States:
    def __init__(self, sim):
        self._sim = sim

    def __call__(self, entity_id):
        e = self._sim.ent.get(entity_id)
        return e["state"] if e else "unknown"

    def __getitem__(self, entity_id):
        e = self._sim.ent.get(entity_id)
        if e is None:
            return None
        return StateObj(entity_id, e["state"], e["changed"], e["updated"], e["reported"], dict(e.get("attrs", {})),
                        self._sim.with_last_reported)


class This:
    def __init__(self, state, attributes):
        self.state = state
        self.attributes = attributes


def make_env(sandboxed: bool) -> jinja2.Environment:
    cls = jinja2.sandbox.ImmutableSandboxedEnvironment if sandboxed else jinja2.Environment
    env = cls(undefined=jinja2.StrictUndefined)
    env.filters["float"] = ha_float
    env.filters["int"] = ha_int
    return env


def parse_result(text: str):
    """Home Assistant parses a rendered attribute into a native type when it is a literal."""
    s = text.strip()
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return s


class Package:
    """The package's templates, compiled in one environment."""

    def __init__(self, text: str, sandboxed: bool):
        data = yaml.safe_load(text)
        blocks = data["template"]
        trig = [b for b in blocks if "triggers" in b]
        plain = [b for b in blocks if "triggers" not in b]
        assert len(trig) == 1 and len(plain) == 1, "expected one trigger-based and one state-based block"
        self.triggers = trig[0]["triggers"]
        model = trig[0]["sensor"][0]
        ttr = plain[0]["sensor"][0]
        self.model_cfg, self.ttr_cfg = model, ttr
        env = make_env(sandboxed)
        self.model_state = env.from_string(model["state"])
        self.model_attr = env.from_string(model["attributes"]["model"])
        self.ttr_state = env.from_string(ttr["state"])
        self.ttr_attrs = {k: env.from_string(v) for k, v in ttr["attributes"].items()}


class Sim:
    """One Home Assistant instance: the input entities, the clock and the two FE-1 entities."""

    def __init__(self, pkg: Package, power=1000, soc=80, pv=0, reserve=20.0, capacity=31.7, online="on", start=T0,
                 with_last_reported=True, ntp=True):
        self.pkg = pkg
        self.now = start
        self.with_last_reported = with_last_reported
        self.ntp = ntp             # the dongle publishes its poll timestamp only while it has NTP time
        self.ent: dict = {}
        self.model = None          # the model entity's `model` attribute (restored after a restart)
        self.model_state = "unknown"
        self.model_seen = None     # when the model entity last rendered
        for eid, v in ((E_POWER, power), (E_SOC, soc), (E_PV, pv), (E_RESERVE, reserve), (E_CAPACITY, capacity),
                       (E_ONLINE, online), (E_POLLED, self._poll_text() if ntp else "Waiting")):
            self.set(eid, v)

    def _poll_text(self):
        return self.now.strftime("%Y-%m-%d %H:%M:%S")

    # ---- inputs ----------------------------------------------------------------------------------------------------------
    def set(self, eid, value):
        """A new value. Like ESPHome (homeassistant/components/esphome/entry_data.py async_update_state drops a state equal to
        the cached one unless force_update) and like a helper set to its current value, an UNCHANGED value never reaches the
        state machine: none of last_changed / last_updated / last_reported moves."""
        v = value if isinstance(value, str) else (str(float(value)) if isinstance(value, float) else str(value))
        e = self.ent.get(eid)
        if e is None:
            self.ent[eid] = {"state": v, "changed": self.now, "updated": self.now, "reported": self.now}
            return
        if e["state"] != v:
            e["state"], e["changed"], e["updated"], e["reported"] = v, self.now, self.now, self.now

    # ---- rendering ---------------------------------------------------------------------------------------------------------
    def _ctx(self, trigger_id):
        states = States(self)
        return {
            "states": states,
            "is_state": lambda eid, val: states(eid) == val,
            "state_attr": lambda eid, attr: (self.model if (eid == E_MODEL and attr == "model") else None),
            "now": lambda: self.now,
            "as_timestamp": as_timestamp,
            "this": This(self.model_state, {"model": self.model} if self.model is not None else {}),
            "trigger": {"id": trigger_id, "platform": "time_pattern" if trigger_id == "tick" else "state"},
        }

    def fire(self, trigger_id="tick"):
        ctx = self._ctx(trigger_id)
        out = parse_result(self.pkg.model_attr.render(ctx))
        if not isinstance(out, dict):
            raise AssertionError(f"model attribute did not parse to a mapping: {str(out)[:200]}")
        self.model_state = self.pkg.model_state.render(ctx)
        self.model = out
        self.model_seen = self.now
        return out

    def tick(self, power=None, soc=None, pv=None, seconds=60, reported=True):
        """Advance the clock and fire the minute trigger. `reported` = the dongle's polls succeeded meanwhile: the values
        it publishes reach HA only when they changed (ESPHome), and its poll timestamp (to the second) always changes. A
        failed or skipped poll (`reported=False`) publishes nothing at all."""
        self.now += timedelta(seconds=seconds)
        if reported:
            if power is not None:
                self.set(E_POWER, power)
            if soc is not None:
                self.set(E_SOC, soc)
            if self.ntp:
                self.set(E_POLLED, self._poll_text())
        if pv is not None:
            self.set(E_PV, pv)
        return self.fire("tick")

    def replay_poll_text(self):
        """An API reconnect: Home Assistant writes the cached poll text again (same text, new timestamps)."""
        e = self.ent[E_POLLED]
        e["changed"] = e["updated"] = e["reported"] = self.now

    def presented(self):
        """The state-based presentation sensor, rendered now (what dashboards and the card read)."""
        ctx = self._ctx("none")
        state = parse_result(self.pkg.ttr_state.render(ctx))
        attrs = {k: parse_result(t.render(ctx)) for k, t in self.pkg.ttr_attrs.items()}
        return state, attrs


PKGS = {"plain": Package(PKG_TEXT, sandboxed=False), "sandbox": Package(PKG_TEXT, sandboxed=True)}
PKG = PKGS["sandbox"]


def warm(sim: Sim, minutes=10, power=None):
    out = None
    for _ in range(minutes):
        out = sim.tick(power)
    return out


def step_round(x: float) -> int:
    x = min(x, 4320)
    step = 1 if x < 10 else (5 if x < 120 else 10)
    return int(round(x / step) * step)


def expected_minutes(soc, reserve, wh_per_pct, power):
    return step_round((soc - reserve) * wh_per_pct / power * 60)


def one_step_apart(a, b) -> bool:
    """Equal, or neighbours on the documented rounding grid (the template's decay constants vs exp() differ in the last bits)."""
    if a == b:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= (1 if max(a, b) < 10 else (5 if max(a, b) < 120 else 10))


# ===========================================================================
print("[0] static: read only, triggers, entities, inputs, renderer rules")
# ===========================================================================
data = yaml.safe_load(PKG_TEXT)
check("the package defines only `template:` (no automation, script, input helper, service or other integration)",
      list(data) == ["template"], str(list(data)))
code = "\n".join(ln.split("#", 1)[0] if not ln.lstrip().startswith("{") else ln for ln in PKG_TEXT.split("\n"))
banned = [w for w in ("action:", "actions:", "service:", "services:", "script.", "automation", "shell_command", "esphome.",
                      "button.press", "input_number.set_value", "conditions:", "rest_command") if w in code]
check("no action, service, script, automation, esphome or helper-setting token outside comments", not banned, str(banned))
check("exactly one trigger-based block (the model) and one state-based block (the presentation sensor)",
      [("triggers" in b) for b in data["template"]] == [True, False])
trig = {(t["trigger"], t.get("id"), t.get("entity_id"), t.get("event"), t.get("minutes")) for t in PKG.triggers}
check("triggers: the one-minute sampling tick, start, the reserve and capacity helpers, the online flag and SOC",
      trig == {("time_pattern", "tick", None, None, "/1"), ("homeassistant", "start", None, "start", None),
               ("state", "config", E_RESERVE, None, None), ("state", "config", E_CAPACITY, None, None),
               ("state", "liveness", E_ONLINE, None, None), ("state", "soc", E_SOC, None, None)}, str(trig))
check("the entities: the model (timestamp state) and the time-to-reserve sensor (minutes, duration)",
      PKG.model_cfg["unique_id"] == "ecco_battery_runtime_model" and PKG.model_cfg["device_class"] == "timestamp"
      and PKG.ttr_cfg["unique_id"] == "ecco_battery_time_to_reserve" and PKG.ttr_cfg["unit_of_measurement"] == "min"
      and PKG.ttr_cfg["device_class"] == "duration" and "state_class" not in PKG.ttr_cfg)


def fw_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


fw_names = {fw_slug(n) for n in re.findall(r'^\s+name:\s*"([^"]+)"\s*$', FIRMWARE, re.M)}
check("every dongle input exists in the firmware (entity ids derived from the ESPHome names, default slug)",
      all(e.split(".", 1)[1].removeprefix("ecco_clock_dongle_") in fw_names for e in (E_POWER, E_SOC, E_PV, E_ONLINE, E_POLLED)),
      str([e for e in (E_POWER, E_SOC, E_PV, E_ONLINE, E_POLLED)
           if e.split(".", 1)[1].removeprefix("ecco_clock_dongle_") not in fw_names]))
check("the liveness timestamp is the dongle's per-poll text (strftime to the second, published on every successful poll while "
      "NTP time is valid), so it changes even when every reading is unchanged",
      'id(last_telemetry_update).publish_state(now.strftime("%Y-%m-%d %H:%M:%S"));' in FIRMWARE)
inp = re.search(r"\ninput_number:\n((?:  .*\n|\n)*)", CORE_PKG)
helper_ids = set(re.findall(r"^  ([a-z0-9_]+):\s*$", inp.group(1), re.M)) if inp else set()
check("the reserve and capacity helpers exist in ecco_pro.yaml (input_number.ecco_minimum_reserve_soc, "
      "input_number.ecco_battery_model_capacity)", {"ecco_minimum_reserve_soc", "ecco_battery_model_capacity"} <= helper_ids,
      str(sorted(helper_ids)[:8]))
check("the battery power sign the package assumes (positive = discharge) is the firmware's documented convention",
      "positive = discharge" in FIRMWARE.lower() and "POSITIVE = DISCHARGE" in PKG_TEXT)
slug_spots = [m.start() for m in re.finditer("ecco_clock_dongle", PKG_TEXT)]
sys.path.insert(0, str(ROOT / "tools"))
import ecco_site_render as render  # noqa: E402

site = render.parse_site({"schema": "ecco-site/1", "device_slug": "site_battery_dongle"})
rendered, counts = render.render_text(PKG_REL, PKG_TEXT, site, render.firmware_actions(ROOT))
check("the default device slug appears only as dongle entity ids (the site renderer's exact rules): the renderer rewrites every "
      "occurrence for another device slug and leaves none behind",
      counts.get("entity", 0) == len(slug_spots) and "sensor.ecco_clock_dongle_" not in rendered
      and "sensor.site_battery_dongle_ecco_battery_output_power" in rendered, str(counts))
reserve_lines = [ln for ln in PKG_TEXT.split("\n") if "reserve" in ln.lower() and not ln.lstrip().startswith("#")]
check("no built-in reserve value: the reserve is read from the helper and never assigned a number",
      not [ln for ln in reserve_lines if re.search(r"reserve\s*=\s*[0-9]", ln) or re.search(r"\b(40|15|10)\s*%", ln)]
      and "{%- set reserve = states(e_reserve) | float(none) -%}" in PKG_TEXT)

for flavour, pkg in PKGS.items():
    s = Sim(pkg)
    out = warm(s, 12)
    check(f"[{flavour}] the templates render in a {'sandboxed' if flavour == 'sandbox' else 'plain'} Jinja environment "
          "with strict undefined values", out["status"] == "discharging", str(out.get("status")))

# ===========================================================================
print("")
print("[1] constant discharge")
# ===========================================================================
for soc, reserve, power, cap in ((80, 20, 1000, 31.7), (55, 40, 650, 31.7), (95, 10, 3200, 32.0), (23, 20, 400, 16.0)):
    s = Sim(PKG, power=power, soc=soc, reserve=reserve, capacity=cap)
    out = warm(s, 12)
    want = expected_minutes(soc, reserve, cap * 10, power)
    check(f"SOC {soc} %, reserve {reserve} %, {power} W, {cap} kWh: {want} min (= (SOC - reserve) x {cap * 10:.0f} Wh/% / power)",
          out["status"] == "discharging" and out["minutes"] == want and out["discharge_w"] == power
          and out["capacity_basis"] == "configured", f"{out['status']} {out['minutes']} vs {want}")
s = Sim(PKG, power=1000, soc=80, reserve=20)
out = warm(s, 12)
check("the range is the honest bracket: low assumes one SOC point less (integer SOC); a steady load has no lighter 5-minute block, so high equals the point estimate",
      out["minutes_low"] == expected_minutes(79, 20, 317, 1000) and out["minutes_high"] == out["minutes"])
check("the summary says 'About', names the configured reserve and calls it an estimate (never a guarantee)",
      out["summary"].startswith("About 19 h") and "20 % reserve" in out["summary"] and "estimate" in out["summary"], out["summary"])
check("rounding: 1 min below 10, 5 min below 2 h, 10 min above (no false precision)",
      [step_round(x) for x in (7.4, 9.6, 33.0, 117.4, 121.0, 1144.0)] == [7, 10, 35, 115, 120, 1140])

# ===========================================================================
print("")
print("[2] restart and insufficient history")
# ===========================================================================
s = Sim(PKG)
seq = [s.tick()["status"] for _ in range(12)]
check("a new model is 'insufficient data' (warming up) for its first 9 minutes, then estimates from the 10th",
      seq[:9] == ["insufficient_data"] * 9 and seq[9:] == ["discharging"] * 3, str(seq))
check("while warming up the reason and summary say so, with progress", s.model["n"] == 12
      and Sim(PKG).tick()["summary"] == "Insufficient data: collecting recent usage (1 of 10 minutes)")
st, at = s.presented()
check("a fresh model's estimate is presented", st == s.model["minutes"] and at["status"] == "discharging")
# short restart: Home Assistant down 4 minutes, the model's attributes restored
s.now += timedelta(minutes=4)
s.set(E_POWER, "unavailable")
s.set(E_ONLINE, "unavailable")
o_start = s.fire("start")
s.set(E_POWER, 1000)
s.set(E_ONLINE, "on")
o_after = s.tick(seconds=30)
check("restart: at start (inputs unavailable) it reports stale, not an old estimate",
      o_start["status"] == "stale" and o_start["minutes"] is None, str(o_start["status"]))
check("a restart shorter than 5 minutes keeps the smoothing history (no new warm-up)",
      o_after["status"] == "discharging" and o_after["reset_reason"] == "start" and o_after["n"] == 13, str(o_after["n"]))
s2 = Sim(PKG)
warm(s2, 15)
s2.model["learned_wh_per_pct"], s2.model["learn_obs"] = 290.0, 4
s2.now += timedelta(minutes=12)
o = s2.tick()
check("a gap longer than 5 minutes restarts the history (warming up again) but keeps the measured capacity",
      o["status"] == "insufficient_data" and o["reason"] == "warming_up" and o["reset_reason"] == "gap" and o["n"] == 1
      and o["learned_wh_per_pct"] == 290.0 and o["learn_obs"] == 4)
seq = [s2.tick()["status"] for _ in range(10)]
check("...and estimates again after 10 minutes, with the measured capacity", seq[-2:] == ["discharging"] * 2
      and s2.model["capacity_basis"] == "measured" and s2.model["capacity_kwh"] == 29.0, str(seq))
s3 = Sim(PKG)
o = s3.fire("start")
check("a first start with no stored model reports insufficient data, never zero minutes",
      o["status"] == "insufficient_data" and o["minutes"] is None and o["n"] == 0)

# ===========================================================================
print("")
print("[3] short load spikes and sustained steps")
# ===========================================================================
for spike_min, spike_w, max_change in ((1, 3000, 0.04), (3, 3000, 0.09), (4, 9000, 0.30)):
    s = Sim(PKG, power=500)
    base = warm(s, 30)["minutes"]
    outs = [s.tick(spike_w if k < spike_min else 500) for k in range(40)]
    # The clipped energy (excess x minutes / 30) stays in the 30-minute window for 30 minutes and feeds the 3-hour average each
    # minute: the allowance takes about excess x minutes / 180 W in total (a little less for the decay meanwhile).
    allowance = (spike_w - 500) * spike_min / 180.0
    worst = max(abs(o["minutes"] / base - 1) for o in outs)
    peak = max(o["spike_allowance_w"] for o in outs)
    check(f"a {spike_min}-minute {spike_w} W spike on a 500 W base: the winsorized usage never moves, the allowance takes its clipped "
          f"energy (about {allowance:.0f} W over 3 h; peak {peak} W) and the estimate moves by at most {max_change:.0%} ({worst:.1%})",
          all(o["usage_w"] == 500 for o in outs) and 0.85 <= peak / allowance <= 1.02 and worst <= max_change,
          f"{[o['spike_allowance_w'] for o in outs[:35:5]]} {worst:.3f}")
s = Sim(PKG, power=500)
warm(s, 30)
s.tick(3000)
s.tick(3000)
s.tick(3000)
after = [s.tick(500)["spike_allowance_w"] for _ in range(210)]
check("...a single kettle's allowance builds while it is in the window (30 minutes), then decays with the 3-hour time constant "
      "(never negative)", 24 <= after.index(max(after)) <= 30, str(after[22:32]))
pk = after.index(max(after))
check("...from its peak, 150 minutes later it holds exp(-150/180) of it", abs(after[pk + 150] / after[pk] - math.exp(-150 / 180)) < 0.08
      and min(after) >= 0, f"{after[pk]} -> {after[pk + 150]}")
s = Sim(PKG, power=500)
warm(s, 20)
outs = [s.tick(2000) for _ in range(50)]
lv = [o["usage_w"] for o in outs]
dw = [o["discharge_w"] for o in outs]
check("a sustained step 500 -> 2000 W (oven): the winsorized usage ignores its first 4 minutes, then counts it in full",
      lv[3] == 500 and lv[4] > 500, str(lv[:8]))
check("...then rises linearly over the 30-minute window: 63 % of the step within 20 minutes, the full step within 27",
      lv[19] >= 500 + 0.63 * 1500 and lv[26] >= 1990, f"{lv[19]} {lv[26]}")
check("...while the discharge estimate takes the sustained run's lower median at once: 2000 W from the 5th minute (fast attack, "
      "errs short)", dw[3] < 600 and dw[4] >= 2000 and min(dw[4:]) >= 2000, str(dw[:8]))
check("...and settles within 2 % of the new load (the step's first minutes leave a small allowance)",
      abs(dw[-1] / 2000 - 1) < 0.02, str(dw[-1]))
s = Sim(PKG, power=2000)
warm(s, 30)
outs = [s.tick(400) for _ in range(50)]
lv = [o["usage_w"] for o in outs]
check("a sustained step down 2000 -> 400 W: the usage follows the same way and the estimate relaxes with it (slow release: it errs "
      "short meanwhile, never long)", lv[3] == 2000 and lv[26] <= 410 and all(o["discharge_w"] >= 400 for o in outs)
      and abs(outs[-1]["discharge_w"] / 400 - 1) < 0.03, f"{lv[3]} {lv[26]} {outs[-1]['discharge_w']}")

# ===========================================================================
print("")
print("[4] variable household load")
# ===========================================================================
def run_trace(base_fn, spike_rate, spike_w, minutes, seed):
    rng = random.Random(seed)
    s = Sim(PKG, power=round(base_fn(0)))
    warm(s, 15)
    rows = []
    for minute in range(minutes):
        spike = spike_w if rng.random() < spike_rate else 0
        p = max(50, base_fn(minute) + spike + rng.gauss(0, 60))
        out = s.tick(round(p))
        rows.append((minute, base_fn(minute) + spike_rate * spike_w, out))
    return s, rows


def errors(rows, start):
    return [out["discharge_w"] / expect - 1 for minute, expect, out in rows if minute >= start]


def wave(m):
    return 600 + 250 * math.sin(m / 47.0)


s, rows = run_trace(wave, 0.0, 0, 360, 11)
abs_err = [out["discharge_w"] - expect for minute, expect, out in rows if minute >= 30]
mean_rel = sum(errors(rows, 30)) / len(abs_err)
# A rise is taken from the run at once; a fall follows the 30-minute window, which lags by about 15 minutes: on a 250 W swing
# with a 5-hour period that bounds the error near 250 * 15 / 47 = 80 W, on the short side.
check(f"(a) a slowly varying load (600 +/- 250 W, a 5-hour cycle) is tracked within 90 W (15 % of its mean) every minute "
      f"(worst {max(map(abs, abs_err)):.0f} W), erring on the short side on average (fast attack, slow release: mean error "
      f"{mean_rel:+.1%}, between 0 and +6 %)", max(map(abs, abs_err)) <= 90 and 0 <= mean_rel < 0.06)
s, rows = run_trace(lambda m: 600, 0.05, 2600, 600, 12)
err = errors(rows, 240)
med = sorted(err)[len(err) // 2]
lvl = sorted(out["usage_w"] / expect - 1 for minute, expect, out in rows if minute >= 240)[len(err) // 2]
p95 = sorted(map(abs, err))[int(len(err) * 0.95)]
check(f"(b) frequent kettle-size spikes (2.6 kW in 5 % of minutes at random, a true mean of 730 W): once the 3-hour allowance has "
      f"learned, the median error is within 6 % ({med:+.1%}; the winsorized usage alone would be {lvl:+.1%}) and within 25 % "
      f"in 95 % of minutes ({p95:.1%}); the worst minutes ({max(map(abs, err)):.0%}) are windows where 5 or more spikes cluster "
      "within 30 minutes (Poisson, about 2 % of windows), which then count in full as real recent usage",
      abs(med) < 0.06 and lvl < -0.10 and p95 <= 0.25 and max(map(abs, err)) < 0.75)
s, rows = run_trace(wave, 0.05, 2600, 600, 13)
err = errors(rows, 240)
abs_err = [out["discharge_w"] - expect for minute, expect, out in rows if minute >= 240]
# Bound: the 75 W lag of (a) plus three standard deviations of the allowance, a 3-hour average of a spike process with
# sd 2600 * sqrt(0.05 * 0.95) = 567 W per minute: 567 * sqrt(a / (2 - a)), a = 1/180, is 30 W, so 75 + 3 * 30 = 165 W.
check(f"(c) both together, after 4 h: within 165 W of the expected load (the varying base plus the spikes' mean) every minute "
      f"(worst {max(map(abs, abs_err)):.0f} W; bound = the lag of (a) + 3 sd of the allowance) and unbiased within 8 % "
      f"(mean error {sum(err) / len(err):+.1%})", max(map(abs, abs_err)) <= 165 and abs(sum(err) / len(err)) < 0.08)
check("the likely range brackets the point estimate whenever discharging",
      s.model["minutes_low"] <= s.model["minutes"] <= s.model["minutes_high"])


def cycling(on_w, base_w, on_min, period, minutes, soc=60, seed=None):
    """A load switching on for `on_min` of every `period` minutes (an oven at temperature, a hob); seed -> random phase/duty."""
    s = Sim(PKG, power=base_w, soc=soc)
    rng = random.Random(seed) if seed is not None else None
    outs = []
    for m in range(minutes):
        on = (rng.random() < on_min / period) if rng else (m % period) < on_min
        outs.append(s.tick(base_w + (on_w if on else 0)))
    return s, outs


for base_w in (0, -150):
    s, outs = cycling(2500, base_w, 2, 5, 120)
    true = base_w + 2500 * 2 / 5
    later = [o for o in outs[30:]]
    check(f"(review N1) an oven cycling 2 of every 5 minutes at 2.5 kW on a {base_w} W base (true discharge {true:.0f} W): "
          "'discharging' from the 30th minute on (never 'holding' or 'charging'), the estimate within 15 % of the true average",
          all(o["status"] == "discharging" for o in later) and all(abs(o["discharge_w"] / true - 1) <= 0.15 for o in outs[60:]),
          f"{sorted({o['status'] for o in later})} {[o['discharge_w'] for o in outs[58:62]]}")
s, outs = cycling(2500, 300, 4, 9, 240)
true = 300 + 2500 * 4 / 9
o = outs[-1]
check(f"(review N2) a regular load under a median's radar (2.5 kW on 4 of every 9 minutes on a 300 W base, true {true:.0f} W): the "
      f"estimate is within 15 % of the true average after 30 minutes and stays there ({o['discharge_w']} W)",
      all(abs(x["discharge_w"] / true - 1) <= 0.15 for x in outs[30:]),
      str([x["discharge_w"] for x in outs[28:34]]))
check("...and the likely range contains the time at the true average",
      o["minutes_low"] <= expected_minutes(60, 20, 317, true) <= o["minutes_high"],
      f"{o['minutes_low']}..{o['minutes_high']} vs {expected_minutes(60, 20, 317, true)}")
true = 2500 * 7 / 20
rel, statuses = [], []
for seed in range(5, 11):
    s, outs = cycling(2500, 0, 7, 20, 240, seed=seed)
    rel += [x["discharge_w"] / true - 1 for x in outs[60:]]
    statuses += [x["status"] for x in outs[60:]]
rel.sort()
share = statuses.count("discharging") / len(statuses)
sigma = 2500 * math.sqrt(0.35 * 0.65 / 30) / true          # sd of a 30-minute window of this random load, relative
within = sum(1 for r in rel if abs(r) <= 2 * sigma) / len(rel)
check(f"(review N1) a randomly switching hob (2.5 kW at a random 35 % duty, true {true:.0f} W), six seeds, after 1 h: unbiased "
      f"(median error {rel[len(rel) // 2]:+.1%}, within 8 %), within two window standard deviations (+/-{2 * sigma:.0%}) in "
      f"{within:.0%} of minutes (at least 85 %), 'discharging' in {share:.0%} of minutes (at least 90 %; a random run of 8 "
      "off-minutes reads as holding)", abs(rel[len(rel) // 2]) <= 0.08 and within >= 0.85 and share >= 0.90)
rng = random.Random(9)
s = Sim(PKG, power=50, soc=60)
seq = [s.tick(50 + rng.randint(-15, 15))["status"] for _ in range(60)]
flips = sum(1 for a, b in zip(seq[10:], seq[11:]) if a != b)
check(f"(review N3) a load hovering at 50 +/- 15 W does not flap between holding and discharging (hysteresis): {flips} changes "
      "in 50 minutes", flips <= 1, str(seq[10:]))
rng = random.Random(77)
s = Sim(PKG, power=600, soc=80)
for _ in range(240):
    s.tick(600 + (2600 if rng.random() < 0.05 else 0))
learned = s.model["spike_allowance_w"]
for _ in range(60):
    s.tick(3100)
outs = [s.tick(600 + (2600 if rng.random() < 0.05 else 0)) for _ in range(120)]
kept = min(o["spike_allowance_w"] for o in outs)
late = [o["discharge_w"] / 730 - 1 for o in outs[60:]]
check(f"(review A) a 60-minute oven in a kettle household does not wipe the allowance (learned {learned} W, lowest afterwards "
      f"{kept} W), and 1-2 h after it the estimate is within 12 % of the true 730 W on average ({sum(late) / len(late):+.1%})",
      learned > 60 and kept >= 0.6 * learned and abs(sum(late) / len(late)) <= 0.12, f"{learned} {kept}")
s = Sim(PKG, power=500, soc=60)
s.tick(500)
for _ in range(3):
    s.tick(3000)
outs = [s.tick(500) for _ in range(8)]
check("(review E) a kettle in the 2nd-4th minute after a start is clipped out of the usage by the end of the warm-up (usage exactly "
      "500 W; before, it leaked in at 2.5x); its energy enters only the 3-hour allowance, so the first estimates are within 5 % of "
      "the 500 W ones", all(o["usage_w"] == 500 for o in outs[-3:]) and outs[-1]["status"] == "discharging"
      and all(abs(o["minutes"] / expected_minutes(60, 20, 317, 500) - 1) <= 0.05 for o in outs[-3:]),
      str([(o["usage_w"], o["minutes"]) for o in outs]))
s = Sim(PKG, power=500, soc=60)
warm(s, 40)
s.tick(3000)
s.tick(3000)
s.tick(3000)
outs = [s.tick(500) for _ in range(30)]
check("(review F) one kettle does not halve the short end of the likely range: within 85 % of the estimate throughout the next "
      "30 minutes (the range is built from the clipped window)", all(o["minutes_low"] >= 0.85 * o["minutes"] for o in outs),
      str(min(o["minutes_low"] / o["minutes"] for o in outs)))
# A 3-minute +2.5 kW kettle is 7500 W-minutes of clipped energy, 250 W over the 30-minute window. At steady state it feeds the
# 3-hour average for 30 minutes, so the allowance peaks at 250 * (1 - 0.994459848 ** 30) = 38.4 W.
KETTLE_PEAK = 2500 * 3 / 30 * (1 - 0.994459848 ** 30)
peaks = {}
for enter in (1, 5, 10, 15, 20, None):
    s = Sim(PKG, power=500, soc=60)
    warm(s, 40)
    if enter is not None:
        s.now += timedelta(minutes=12)                      # a gap: the window restarts, the allowance (0 here) is kept
        s.tick(500)
        for _ in range(enter - 1):
            s.tick(500)
    outs = [s.tick(3000 if k < 3 else 500) for k in range(45)]
    peaks[enter] = max(o["spike_allowance_w"] for o in outs)
    if enter is not None and enter < 10:
        before = [o["spike_allowance_w"] for o in outs[:9 - enter]]   # the samples up to the 9th: still warming up
        peaks[f"warm-up {enter}"] = max(before) if before else 0
check(f"(review 4) a kettle's allowance is its clipped energy over the 30-minute window also while the window refills after a "
      f"gap: the peak is never above the steady-state {KETTLE_PEAK:.1f} W, and the steady-state peak matches it "
      f"(peaks by the number of 500 W samples before it, None = no gap: {peaks})",
      all(peaks[e] <= KETTLE_PEAK + 1 for e in (1, 5, 10, 15, 20)) and abs(peaks[None] - KETTLE_PEAK) <= 1.5
      and all(peaks[e] >= 0.9 * KETTLE_PEAK for e in (10, 15, 20)))
check("(review 4) the allowance does not learn during the warm-up after a gap: a kettle in its 2nd-8th sample leaves it at 0 W "
      "through the 9th", peaks["warm-up 1"] == 0 and peaks["warm-up 5"] == 0, str(peaks))
s = Sim(PKG, power=500, soc=60)
base = warm(s, 40)["minutes"]
outs = [s.tick(3000 if k < 5 else 500) for k in range(36)]
check("(documented, review C) a single 5-minute 2.5 kW load counts as real usage at once: the estimate is short while it is in the "
      "recent minutes, and back within 10 % of the 500 W one within about 30 minutes of its start",
      min(o["minutes"] for o in outs[:8]) < 0.5 * base and abs(outs[-1]["minutes"] / base - 1) <= 0.10,
      f"{base} {[o['minutes'] for o in outs[::5]]}")

# ===========================================================================
print("")
print("[5] charging, holding, solar-assisted discharge")
# ===========================================================================
s = Sim(PKG, power=-2500)
out = warm(s, 12)
st, at = s.presented()
check("charging: status 'charging', no minutes (the sensor state is unknown), summary 'Charging'",
      out["status"] == "charging" and out["minutes"] is None and st is None and at["status"] == "charging"
      and at["summary"] == "Charging")
s = Sim(PKG, power=0)
out = warm(s, 12)
check("zero discharge: 'holding', no minutes", out["status"] == "holding" and out["minutes"] is None)
s = Sim(PKG, power=30)
out = warm(s, 12)
check("insufficient discharge (30 W, below the 50 W hold band): 'holding', never days of runtime",
      out["status"] == "holding" and out["minutes"] is None)
s = Sim(PKG, power=0)
warm(s, 2)
out = None
for k in range(20):
    out = s.tick(45 if k % 2 else -45)
check("idle noise alternating +/-45 W: 'holding'", out["status"] == "holding")
s = Sim(PKG, power=300, pv=1800)
out = warm(s, 12)
check("solar-assisted: the net battery discharge (300 W with 1800 W of solar) drives the estimate, flagged solar-assisted",
      out["status"] == "discharging" and out["minutes"] == expected_minutes(80, 20, 317, 300) and out["solar_assisted"] is True)
s = Sim(PKG, power=-900, pv=3200)
out = warm(s, 12)
check("solar covering the load and charging: 'charging', not solar-assisted", out["status"] == "charging"
      and out["solar_assisted"] is False)
s = Sim(PKG, power=1200, pv=0)
out = warm(s, 12)
check("no solar: not flagged solar-assisted", out["solar_assisted"] is False)
rng = random.Random(41)
s = Sim(PKG, power=600, soc=60)
for _ in range(180):
    s.tick(600 + (2600 if rng.random() < 0.05 else 0))
allow = s.model["spike_allowance_w"]
seq = [s.tick(rng.choice([-3, 0, 3]))["status"] for _ in range(60)]
check(f"(review S1) idle after three hours of spiky discharge (allowance {allow} W): 'holding' from the 8th idle minute (a "
      "sustained idle run) and from then on, never a days-long 'discharging' estimate", allow > 50 and seq[7:] == ["holding"] * 53,
      str(seq[:10]))
s = Sim(PKG, power=-1500, soc=50)
for k in range(120):
    s.tick(-1500 - (1800 if k % 11 == 0 else 0) + (1200 if k % 17 == 0 else 0))
check("(review S2/S3) brief sun bursts and cloud dips while charging do not change the allowance (it learns only while "
      "discharging)", s.model["spike_allowance_w"] == 0, str(s.model["spike_allowance_w"]))
outs = [s.tick(150) for _ in range(12)]
check("(review S3) a real 150 W discharge after charging: 'discharging' from the 8th minute (a sustained run), never held at "
      "'charging'", [o["status"] for o in outs[7:]] == ["discharging"] * 5, str([o["status"] for o in outs]))
outs = [s.tick(400) for _ in range(40)]
check("(review S3) a real 400 W discharge is estimated within 2 % of 400 W (no carried-over negative allowance; only the small, "
      "decaying allowance of the step itself) and the minutes follow that discharge: not 2x optimistic",
      abs(outs[-1]["discharge_w"] / 400 - 1) <= 0.02
      and one_step_apart(outs[-1]["minutes"], expected_minutes(50, 20, 317, outs[-1]["discharge_w"])),
      f"{outs[-1]['discharge_w']} {outs[-1]['minutes']}")
s = Sim(PKG, power=500, soc=60)
s.tick(3000)
outs = [s.tick(500) for _ in range(10)]
check("(review: seeding) a kettle minute as the very first sample after a start does not linger: at the end of the warm-up the "
      "estimate is the 500 W one (it is clipped)", outs[-1]["status"] == "discharging"
      and one_step_apart(outs[-1]["minutes"], expected_minutes(60, 20, 317, 500)),
      f"{outs[-1]['minutes']} vs {expected_minutes(60, 20, 317, 500)}")
s = Sim(PKG, power=500, soc=60)
warm(s, 20)
outs = [s.tick(1500) for _ in range(8)]
check("fast attack: a sustained rise 500 -> 1500 W is in the discharge estimate by its 5th minute (the run's lower median), "
      "before the 30-minute usage catches up: the estimate errs on the short side",
      outs[4]["discharge_w"] >= 1500 and outs[4]["usage_w"] < 1100, f"{outs[4]['discharge_w']} usage {outs[4]['usage_w']}")
s = Sim(PKG, power=-1500)
warm(s, 12)
seq = [s.tick(1500)["status"] for _ in range(25)]
check("charging -> discharging (e.g. at sunset): the status changes once a sustained run shows it, without flapping",
      seq[:3] == ["charging"] * 3 and seq[-1] == "discharging"
      and sum(1 for a, b in zip(seq, seq[1:]) if a != b) <= 2, str(seq))

# ===========================================================================
print("")
print("[6] reserve: reached, changed, unavailable; nothing hard-coded")
# ===========================================================================
s = Sim(PKG, power=900, soc=20, reserve=20)
out = warm(s, 12)
st, at = s.presented()
check("SOC at the reserve while discharging: 'at_reserve', 0 minutes", out["status"] == "at_reserve" and out["minutes"] == 0
      and st == 0 and at["status"] == "at_reserve")
s = Sim(PKG, power=900, soc=12, reserve=20)
out = warm(s, 12)
check("SOC below the reserve: 'at_reserve', 0 minutes, never negative", out["status"] == "at_reserve" and out["minutes"] == 0)
s = Sim(PKG, power=-800, soc=15, reserve=20)
out = warm(s, 12)
check("below the reserve and charging: 'charging'", out["status"] == "charging")
s = Sim(PKG, power=0, soc=20, reserve=20)
out = warm(s, 12)
check("at the reserve and idle: 'at_reserve'", out["status"] == "at_reserve")
s = Sim(PKG, power=1000, soc=80, reserve=20)
warm(s, 12)
outs = {}
for r in (0, 15, 40, 79.0, 55.5):
    s.set(E_RESERVE, r)
    outs[r] = s.fire("config")["minutes"]
check("any configured reserve is used as set (0, 15, 40, 79, 55.5 %), applied at once on the helper change (no tick needed)",
      all(outs[r] == expected_minutes(80, r, 317, 1000) for r in outs), str(outs))
check("the minutes scale with SOC - reserve (proportionality across reserves)",
      abs(outs[0] / outs[40] - 2.0) < 0.02, str(outs))
for bad in ("unavailable", "unknown", "abc", "100", "-1"):
    s.set(E_RESERVE, bad)
    out = s.fire("config")
    check(f"reserve {bad!r}: insufficient data (reserve unavailable), never a guessed reserve",
          out["status"] == "insufficient_data" and out["reason"] == "reserve_unavailable" and out["minutes"] is None)

# ===========================================================================
print("")
print("[7] missing and stale telemetry")
# ===========================================================================
s = Sim(PKG)
warm(s, 12)
s.set(E_ONLINE, "off")
out = s.fire("liveness")
check("telemetry offline: 'stale' at once (liveness trigger), no minutes", out["status"] == "stale"
      and out["reason"] == "telemetry_offline" and out["minutes"] is None)
s.set(E_ONLINE, "on")
out = s.tick()
check("back online within the gap: estimating again without a warm-up", out["status"] == "discharging")
s = Sim(PKG)
warm(s, 12)
s.set(E_POWER, "unavailable")
out = s.tick()
check("battery power unavailable: 'stale' (battery power unavailable)", out["status"] == "stale"
      and out["reason"] == "battery_power_unavailable")
s = Sim(PKG)
warm(s, 12)
seq = []
for _ in range(6):
    seq.append(s.tick(reported=False)["status"])
check("reports stop although the online flag stays on (a skipped poll keeps old values): 'stale' once the report is over "
      "180 s old", seq[:3] == ["discharging"] * 3 and seq[3:] == ["stale"] * 3, str(seq))
check("...and stale samples are never taken into the history (12 + the 3 still-fresh minutes)", s.model["n"] == 15,
      str(s.model["n"]))
s = Sim(PKG, power=0, soc=60)
seq = [s.tick(0)["status"] for _ in range(70)]
check("an unchanged reading (0 W while idle for over an hour, which ESPHome never re-sends): 'holding' throughout after the "
      "warm-up, never 'stale' (liveness is the per-poll timestamp, not the power value)",
      seq[9:] == ["holding"] * 61 and s.model["telemetry_age_s"] <= 60, str(sorted(set(seq[9:]))))
s = Sim(PKG, power=900, soc=20, reserve=20)
seq = [s.tick(900)["status"] for _ in range(40)]
check("...and an unchanged reading at the reserve stays 'at_reserve' (reachable, not masked as stale)",
      seq[9:] == ["at_reserve"] * 31, str(sorted(set(seq[9:]))))
s = Sim(PKG, power=700, soc=60)
warm(s, 12)
seq = [s.tick(reported=False)["status"] for _ in range(2)]
s.replay_poll_text()
seq += [s.tick(reported=False)["status"] for _ in range(3)]
check("(review N5) a reconnect that replays the old poll text (new last_changed, same text) does not count as fresh: 'stale' once "
      "the text has not changed for 180 s", seq[-1] == "stale" and s.model["n"] == 15, f"{seq} n={s.model['n']}")
s = Sim(PKG, power=0, soc=60, ntp=False)
seq = [s.tick(0)["status"] for _ in range(15)]
check("without NTP time the dongle publishes no poll timestamp ('Waiting'): the power report age is the fallback, so a constant "
      "reading turns 'stale' after 180 s (documented limitation)", seq[1] != "stale" and seq[-1] == "stale", str(seq))
s = Sim(PKG, power=500, soc=60, ntp=False)
rng = random.Random(3)
seq = [s.tick(500 + rng.choice([-7, -3, 2, 5, 9]))["status"] for _ in range(15)]
check("...while a changing reading stays fresh on the fallback", seq[-3:] == ["discharging"] * 3, str(seq))
s = Sim(PKG)
warm(s, 12)
for _ in range(9):
    s.tick(reported=False)
out = s.tick()
check("after more than 5 minutes stale, fresh data restarts the history (warming up)", out["status"] == "insufficient_data"
      and out["reset_reason"] == "gap")

# ===========================================================================
print("")
print("[8] inconsistent SOC")
# ===========================================================================
s = Sim(PKG)
warm(s, 12)
for bad, reason in (("unavailable", "soc_unavailable"), ("abc", "soc_unavailable"), ("101", "soc_out_of_range"),
                    ("-3", "soc_out_of_range")):
    s.set(E_SOC, bad)
    out = s.fire("soc")
    check(f"SOC {bad!r}: insufficient data ({reason})", out["status"] == "insufficient_data" and out["reason"] == reason)
s.set(E_SOC, 80)
s = Sim(PKG, soc=80)
warm(s, 12)
out = s.tick(soc=70)
check("an SOC jump of 10 points in a minute restarts the history (reset reason soc_jump)", out["reset_reason"] == "soc_jump"
      and out["status"] == "insufficient_data" and out["n"] == 1)
s = Sim(PKG, soc=0, power=900)
out = warm(s, 12)
check("SOC 0 % while discharging 900 W is treated as a suspect reading, not an empty battery",
      out["status"] == "insufficient_data" and out["reason"] == "soc_zero_suspect")

# ===========================================================================
print("")
print("[9] capacity: configured until measured")
# ===========================================================================


def discharge_run(sim: Sim, true_wh: float, power: float, minutes: int, soc0: float, rounding=math.floor):
    """The battery delivers `power` W; the inverter's integer SOC follows the true energy per percent."""
    internal = soc0
    out = None
    for _ in range(minutes):
        internal -= power / 60 / true_wh
        out = sim.tick(power, soc=rounding(internal))
    return out


s = Sim(PKG, power=1500, soc=80, capacity=31.7)
out = discharge_run(s, 285.0, 1500, 120, 80.999)
check("before 3 observations (15 SOC points) the configured capacity is the basis", out["capacity_basis"] == "configured"
      and out["learn_obs"] < 3, f"{out['capacity_basis']} {out['learn_obs']}")
out = discharge_run(s, 285.0, 1500, 260, s.model["soc_sample"] + 0.999)
check("after 3 or more observations the measured energy per percent is the basis (285 Wh/% measured within 3 %)",
      out["capacity_basis"] == "measured" and out["learn_obs"] >= 3 and abs(out["learned_wh_per_pct"] / 285 - 1) < 0.03,
      f"{out['capacity_basis']} {out['learn_obs']} {out['learned_wh_per_pct']}")
check("...and the estimate uses it", out["minutes"] == expected_minutes(out["soc"], 20, out["learned_wh_per_pct"], 1500)
      or abs(out["minutes"] - expected_minutes(out["soc"], 20, out["learned_wh_per_pct"], 1500)) <= 10)
check("the configured capacity stays visible next to the measured one", out["configured_capacity_kwh"] == 31.7
      and out["capacity_kwh"] == round(out["learned_wh_per_pct"] / 10, 1))
learned = out["learned_wh_per_pct"]
obs = out["learn_obs"]
out = s.tick(-1200, soc=s.model["soc_sample"])
check("charging ends the current segment but keeps what was learned", out["learn_anchor_soc"] is None
      and out["learned_wh_per_pct"] == learned and out["learn_obs"] == obs)
s = Sim(PKG, power=1500, soc=80, capacity=31.7)
discharge_run(s, 285.0, 1500, 380, 80.999)
before = (s.model["capacity_basis"], s.model["learned_wh_per_pct"])
s.set(E_CAPACITY, 15.0)
out = s.fire("config")
check("(review) a change of the configured capacity restarts the measuring: the configured value is the basis again",
      before[0] == "measured" and out["capacity_basis"] == "configured" and out["learned_wh_per_pct"] is None
      and out["learn_obs"] == 0 and out["capacity_kwh"] == 15.0 and out["learn_restarts"] == 1, f"{before} -> {out['capacity_basis']}")
s = Sim(PKG, power=1500, soc=80, capacity=31.7)
out = discharge_run(s, 285.0, 1500, 380, 80.999)
learned = out["learned_wh_per_pct"]
out = discharge_run(s, 190.0, 1500, 120, s.model["soc_sample"] + 0.999)
check("(review) a measurement more than 20 % away from the measured value (a module lost: 285 -> 190 Wh/%) restarts the "
      "measuring: the configured value is the basis until 3 new measurements, never the stale measured one",
      out["learn_restarts"] >= 1 and out["learned_wh_per_pct"] != learned and out["capacity_basis"] == "configured",
      f"{learned} -> {out['learned_wh_per_pct']} {out['capacity_basis']} obs {out['learn_obs']}")
out = discharge_run(s, 190.0, 1500, 200, s.model["soc_sample"] + 0.999)
check("...and the new value is used once it is confirmed (190 Wh/% within 3 %)",
      out["capacity_basis"] == "measured" and abs(out["learned_wh_per_pct"] / 190 - 1) < 0.03, str(out["learned_wh_per_pct"]))
s = Sim(PKG, power=1500, soc=80, capacity=31.7)
out = discharge_run(s, 285.0, 1500, 380, 80.999)
learned, obs = out["learned_wh_per_pct"], out["learn_obs"]
out = discharge_run(s, 170.0, 1500, 30, s.model["soc_sample"] + 0.999)
out = discharge_run(s, 285.0, 1500, 120, s.model["soc_sample"] + 0.999)
check("(review N6) a single outlying measurement (an SOC recalibration) is held, not acted on: the measured value and its basis "
      "stay, and the next agreeing measurement clears it", out["capacity_basis"] == "measured" and out["learn_restarts"] == 0
      and abs(out["learned_wh_per_pct"] / learned - 1) < 0.05 and out["learn_outlier_wh"] is None, str(out["learned_wh_per_pct"]))
s = Sim(PKG, power=1500, soc=80, capacity="unavailable")
s.set(E_CAPACITY, "unavailable")
out = discharge_run(s, 285.0, 1500, 380, 80.999)
was = out["learned_for_capacity_kwh"]
s.set(E_CAPACITY, 31.7)
out = s.fire("config")
adopted = out["learned_for_capacity_kwh"]
s.set(E_CAPACITY, 20.0)
out = s.fire("config")
check("(review N7) a capacity measured while the capacity helper was unavailable is adopted when it returns, so a later change "
      "still restarts the measuring", was is None and adopted == 31.7 and out["learn_restarts"] == 1
      and out["capacity_basis"] == "configured", f"{was} {adopted} {out['learn_restarts']}")
s = Sim(PKG, power=1500, soc=80, capacity=31.7)
out = discharge_run(s, 100.0, 1500, 120, 80.999)
check("an implausible measurement (100 Wh/% against 317 configured) is rejected, the configured value stays the basis",
      out["learn_rejected"] >= 1 and out["learn_obs"] == 0 and out["capacity_basis"] == "configured", str(out["learn_rejected"]))
s = Sim(PKG, power=1500, soc=80, capacity="unavailable")
out = warm(s, 12)
check("no configured capacity and nothing measured: insufficient data (capacity unavailable), never a guessed capacity",
      out["status"] == "insufficient_data" and out["reason"] == "capacity_unavailable")
s = Sim(PKG, power=1500, soc=80, capacity=0)
check("a capacity of 0 kWh is not a capacity", warm(s, 12)["reason"] == "capacity_unavailable")
s = Sim(PKG, power=1500, soc=80, capacity=31.7)
discharge_run(s, 300.0, 1500, 340, 80.999, rounding=lambda x: int(round(x)))
check("an inverter that rounds SOC to the nearest point measures the same energy per percent (300 Wh/%, within 3 %)",
      s.model["learn_obs"] >= 3 and abs(s.model["learned_wh_per_pct"] / 300 - 1) < 0.03, str(s.model["learned_wh_per_pct"]))

# ===========================================================================
print("")
print("[10] boundary and numerical stability")
# ===========================================================================
s = Sim(PKG, power=60, soc=100, reserve=0)
out = warm(s, 12)
check("a very long runtime is capped at 72 h and said as 'More than 3 days' (no false precision)",
      out["minutes"] == 4320 and out["beyond_horizon"] is True and out["summary"].startswith("More than 3 days"))
s = Sim(PKG, power=60, soc=60, reserve=20)
check("60 W is the first discharging value (the hold band is open below it)", warm(s, 12)["status"] == "discharging")
s = Sim(PKG, power=59, soc=60, reserve=20)
check("59 W is still holding", warm(s, 12)["status"] == "holding")
s = Sim(PKG, power=-60)
check("-60 W is charging (the band is symmetric)", warm(s, 12)["status"] == "charging")
s = Sim(PKG, power=-59)
check("-59 W is holding", warm(s, 12)["status"] == "holding")
s = Sim(PKG, power=25000, soc=21, reserve=20)
out = warm(s, 12)
check("an extreme discharge (25 kW, 1 point above the reserve) gives a small, non-negative number",
      out["status"] == "discharging" and 0 <= out["minutes"] <= 1 and out["minutes_low"] == 0)
s = Sim(PKG)
warm(s, 12)
for bad in ("nan", "inf", "-inf", "1e12", "", "None"):
    s.set(E_POWER, bad)
    out = s.tick()
    check(f"battery power {bad!r}: stale, no estimate, no exception", out["status"] == "stale" and out["minutes"] is None)
s = Sim(PKG)
warm(s, 12)
outs = [s.tick(seconds=sec) for sec in (95, 30, 150, 60, 61)]
check("irregular tick spacing (30-150 s) keeps estimating with the time-correct smoothing",
      all(o["status"] == "discharging" for o in outs))
s.now -= timedelta(minutes=10)
out = s.tick()
check("a clock that jumps backwards restarts the history instead of producing a negative interval",
      out["reset_reason"] == "gap" and out["n"] == 1)
s = Sim(PKG, power=700, soc=90)
rng = random.Random(7)
days, acc = [], []
for minute in range(7 * 1440):
    out = s.tick(int(700 + rng.gauss(0, 80)))
    acc.append(out["discharge_w"])
    if minute % 1440 == 1439:
        days.append(sum(acc) / len(acc))
        acc = []
check("a simulated week of a noisy 700 W load: every day's mean estimate within 0 to +5 % of 700 W (short-side by design), no "
      f"drift from day 1 to day 7, no overflow, n and the window bounded (daily means {[round(d) for d in days]})",
      all(700 <= d <= 735 for d in days) and abs(days[-1] - days[0]) < 10 and s.model["n"] == 7 * 1440
      and len(s.model["window"]) == 30)
check("the model attribute stays small (under 2.5 kB rendered) for the recorder", len(repr(s.model)) < 2500, str(len(repr(s.model))))

# ===========================================================================
print("")
print("[11] the presentation sensor")
# ===========================================================================
s = Sim(PKG, power=1000, soc=80, reserve=20)
warm(s, 12)
st, at = s.presented()
check("state = the model's minutes; status, summary, range, reserve, discharge, capacity basis and history are lookups",
      st == s.model["minutes"] and at["status"] == "discharging" and at["summary"] == s.model["summary"]
      and at["minutes_low"] == s.model["minutes_low"] and at["minutes_high"] == s.model["minutes_high"]
      and at["reserve_soc"] == 20.0 and at["discharge_w"] == 1000 and at["capacity_basis"] == "configured"
      and at["history_minutes"] == 12 and at["solar_assisted"] is False)
check("the presentation sensor carries the estimate note (not a guarantee, enforces nothing)",
      "not a guarantee" in at["estimate_note"])
s.now += timedelta(minutes=4)
st, at = s.presented()
check("a model that stopped updating (over 180 s) is reported as insufficient data, never as the last estimate, and every "
      "value it carried is withheld (range, discharge, capacity, reserve, energy)",
      st is None and at["status"] == "insufficient_data" and at["reason"] == "model_not_updating"
      and all(at[k] is None for k in ("minutes_low", "minutes_high", "discharge_w", "capacity_kwh", "capacity_basis", "reserve_soc",
                                      "energy_above_reserve_kwh")) and at["beyond_horizon"] is False and at["history_minutes"] == 0)
s.model = None
st, at = s.presented()
check("no model at all: insufficient data", st is None and at["status"] == "insufficient_data")
text_ttr = yaml.safe_dump(PKG.ttr_cfg)
check("the presentation templates contain no arithmetic on SOC, power, reserve or capacity (lookups only)",
      not re.search(r"states\('(sensor|input_number|binary_sensor)\.(?!ecco_battery_runtime_model)", text_ttr)
      and not re.search(r"\be_reserve\b", text_ttr) and "* 60" not in text_ttr)

# ===========================================================================
print("")
print("[12] a second implementation (consistency with the documented method)")
# ===========================================================================


class Oracle:
    """A plain-Python statement of the documented method (written from the docs, not from the template text)."""

    def __init__(self):
        self.w, self.n, self.last, self.soc_s, self.exc, self.direction = [], 0, None, None, 0.0, None
        self.anchor, self.e_wh, self.wh, self.obs, self.pending = None, 0.0, None, 0, None

    @staticmethod
    def tmean(w):
        """Winsorized mean: the k highest clipped to the (k+1)-th highest, the k lowest to the (k+1)-th lowest."""
        srt = sorted(w)
        k = min(4, (len(srt) - 1) // 2)
        lo, hi = srt[k], srt[len(srt) - 1 - k]
        return sum(min(max(x, lo), hi) for x in srt) / len(srt)

    @staticmethod
    def clipped(w):
        """The energy the upper clipping removes, spread over the 30-minute window (also while it refills)."""
        srt = sorted(w)
        k = min(4, (len(srt) - 1) // 2)
        return (sum(srt[len(srt) - k:]) - k * srt[len(srt) - 1 - k]) / 30.0 if k > 0 else 0.0

    def step(self, t, p, soc, reserve, cap_kwh):
        prior = cap_kwh * 10
        dt = None if self.last is None else t - self.last
        added = None
        jump = self.soc_s is not None and abs(soc - self.soc_s) > 5
        if dt is None or dt <= 0 or dt > 300 or jump or not self.w:
            self.w, self.n, self.anchor, self.e_wh = [round(p)], 1, None, 0.0
        else:
            p_prev = self.w[-1]
            self.w = (self.w + [round(p)])[-30:]
            added = dt
            self.n += 1
            e_step = (p + p_prev) / 2 * dt / 3600
            if p < -100 or soc > self.soc_s:
                self.anchor, self.e_wh = None, 0.0
            elif self.anchor is not None:
                self.e_wh += e_step
                if soc < self.soc_s and self.anchor - soc >= 5:
                    s_ = self.e_wh / (self.anchor - soc)
                    if prior * 0.5 <= s_ <= prior * 1.5:
                        if self.obs == 0 or self.wh is None:
                            self.wh, self.obs, self.pending = s_, 1, None
                        elif abs(s_ - self.wh) <= 0.2 * self.wh:
                            self.wh, self.obs, self.pending = self.wh + 0.3 * (s_ - self.wh), self.obs + 1, None
                        elif self.pending is not None and abs(s_ - self.pending) <= 0.2 * self.pending:
                            self.wh, self.obs, self.pending = (s_ + self.pending) / 2, 2, None
                        else:
                            self.pending = s_
                    self.anchor, self.e_wh = soc, 0.0
            elif soc < self.soc_s:
                self.anchor, self.e_wh = soc, 0.0
        self.last, self.soc_s = t, soc
        usage = self.tmean(self.w)
        last8 = self.w[-8:] if len(self.w) >= 8 else []
        run = None
        if len(last8) == 8:
            if min(last8) >= 60:
                run = "discharging"
            elif max(last8) <= -60:
                run = "charging"
            elif min(last8) > -60 and max(last8) < 60:
                run = "holding"
        if self.n >= 10:
            if run is not None:
                self.direction = run
            elif usage <= -60 or (self.direction == "charging" and usage <= -40):
                self.direction = "charging"
            elif usage >= 60 or (self.direction == "discharging" and usage >= 40):
                self.direction = "discharging"
            else:
                self.direction = "holding"
        base = max(usage, sorted(last8)[3]) if run == "discharging" else usage
        if added is not None and self.n >= 10 and self.direction == "discharging":   # the clipped energy, discharging only
            c = self.clipped(self.w)
            self.exc = c + (self.exc - c) * math.exp(-added / 10800.0)
        wh = self.wh if (self.wh is not None and self.obs >= 3) else prior
        if self.n < 10:
            return "insufficient_data", None
        if self.direction == "charging":
            return "charging", None
        if soc <= reserve:
            return "at_reserve", 0
        if self.direction != "discharging":
            return "holding", None
        return "discharging", step_round((soc - reserve) * wh / max(base + self.exc, 40) * 60)


agree, total, exact, worst = 0, 0, 0, []
for seed in range(6):
    rng = random.Random(1000 + seed)
    s = Sim(PKG, power=800, soc=90, reserve=rng.choice([0, 15, 20, 40]))
    o = Oracle()
    internal = 90.999
    reserve = float(s.ent[E_RESERVE]["state"])
    for minute in range(420):
        regime = (minute // 60) % 4
        p = {0: 900, 1: -1200, 2: 30, 3: 1600}[regime] + rng.gauss(0, 120) + (2500 if rng.random() < 0.04 else 0)
        internal = min(100.0, max(0.0, internal - p / 60 / 290.0))
        soc = math.floor(internal)
        out = s.tick(round(p), soc=soc)
        want = o.step(as_timestamp(s.now), round(p), soc, reserve, 31.7)
        total += 1
        if out["status"] == want[0] and one_step_apart(out["minutes"], want[1]):
            agree += 1
            exact += out["minutes"] == want[1]
        else:
            worst.append((seed, minute, (out["status"], out["minutes"]), want))
check(f"a second, plain-Python implementation of the documented algorithm agrees with the templates on the status at every one "
      f"of {total} minutes of six random traces (discharge, charge, idle, heavy load, spikes, learning) and on the minutes to within "
      "one rounding step (a consistency check of the templates against the written method; it cannot catch a flaw in the method)",
      agree == total, str(worst[:3]))
check(f"...with exactly equal minutes in {exact / total:.2%} of them (only rounding-boundary neighbours differ)",
      exact / total > 0.98)

# ===========================================================================
print("")
print("[13] wiring: manifest, dashboard, card vocabulary")
# ===========================================================================
man = yaml.safe_load((ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8"))
st_pk = [p for p in man["home_assistant_packages"] if p["source"] == PKG_REL]
check("the deployment manifest lists the package exactly once (ssh_file_copy to /config/packages, restart required)",
      len(st_pk) == 1 and st_pk[0]["destination"] == "/config/packages/ecco_battery_runtime.yaml"
      and st_pk[0]["method"] == "ssh_file_copy" and st_pk[0]["restart_required"] is True)
dash = (ROOT / "home-assistant" / "dashboards" / "ecco_pro.yaml").read_text(encoding="utf-8")
flow_at = dash.index("          - type: custom:ecco-energy-flow-card\n")
flow_end = dash.index("\n\n", dash.index("            card_mod:", flow_at))
flow = dash[flow_at:flow_end]
check("the Overview Energy Flow card's battery node reads the sensor (nodes.battery.time_to_reserve), once in the dashboard",
      dash.count("custom:ecco-energy-flow-card") == 1 and dash.count("time_to_reserve:") == 1
      and "                power_sign: discharge_positive\n                time_to_reserve: sensor.ecco_battery_time_to_reserve\n" in flow)
check("the Overview battery estimate card shows the sensor's summary (display only)",
      dash.count("states['sensor.ecco_battery_time_to_reserve']") == 1)
display_ts = (ROOT / "frontend" / "ecco-energy-flow-card" / "src" / "utils" / "display.ts").read_text(encoding="utf-8")
m = re.search(r"RESERVE_RUNTIME_STATUSES[^=]*=\s*\[([^\]]*)\]", display_ts)
card_statuses = set(re.findall(r'"([a-z_]+)"', m.group(1))) if m else set()
pkg_statuses = set(re.findall(r"set out\.status = '([a-z_]+)'", PKG_TEXT)) | {"insufficient_data"}
check("the card understands exactly the statuses the package can emit", card_statuses == pkg_statuses == STATUSES,
      f"card {sorted(card_statuses)} package {sorted(pkg_statuses)}")

# ===========================================================================
print("")
print("[14] mutation: each mutant is caught, equivalent rewrites survive")
# ===========================================================================


def scenario_suite(pkg: Package) -> dict:
    """A compact battery of the behaviours above; True means the behaviour holds."""
    r = {}
    try:
        s = Sim(pkg, power=500)
        base = warm(s, 20)["minutes"]
        outs = [s.tick(3000 if k < 3 else 500) for k in range(12)]
        r["spike"] = all(o["usage_w"] == 500 and abs(o["minutes"] / base - 1) <= 0.09 for o in outs)
        s = Sim(pkg)
        warm(s, 12)
        r["stale"] = [s.tick(reported=False)["status"] for _ in range(5)][-1] == "stale"
        s = Sim(pkg, power=-2000)
        r["charging"] = warm(s, 12)["status"] == "charging"
        s = Sim(pkg, power=1000, soc=80, reserve=20)
        warm(s, 12)
        s.set(E_RESERVE, 50)
        r["reserve"] = s.fire("config")["minutes"] == expected_minutes(80, 50, 317, 1000)
        s = Sim(pkg)
        r["warmup"] = [s.tick()["status"] for _ in range(10)][:9] == ["insufficient_data"] * 9
        s = Sim(pkg, power=1500, soc=80)
        discharge_run(s, 285.0, 1500, 380, 80.999)
        r["learning"] = s.model["capacity_basis"] == "measured"
        s = Sim(pkg)
        warm(s, 12)
        s.now += timedelta(minutes=12)
        r["gap"] = s.tick()["status"] == "insufficient_data"
        s = Sim(pkg, power=30)
        r["holding"] = warm(s, 12)["status"] == "holding"
        s = Sim(pkg, power=900, soc=20, reserve=20)
        r["at_reserve"] = warm(s, 12)["status"] == "at_reserve"
        s = Sim(pkg, power=0, soc=60)
        r["idle_fresh"] = [s.tick(0)["status"] for _ in range(20)][-1] == "holding"
        s = Sim(pkg, power=-1500, soc=50)
        for k in range(60):
            s.tick(-1500 + (1800 if k % 7 == 0 else 0))
        r["charge_allowance"] = s.model["spike_allowance_w"] == 0
        s = Sim(pkg, power=500, soc=60)
        s.tick(3000)
        r["seeding"] = one_step_apart([s.tick(500) for _ in range(10)][-1]["minutes"], expected_minutes(60, 20, 317, 500))
        s = Sim(pkg, power=0, soc=60)
        r["duty_cycle"] = [s.tick(2500 if m % 5 < 2 else 0)["status"] for m in range(45)][-1] == "discharging"
        s = Sim(pkg, power=600, soc=60)
        warm(s, 30)
        r["idle_fast"] = [s.tick(0)["status"] for _ in range(10)][-1] == "holding"
        s = Sim(pkg, power=500, soc=60)
        warm(s, 40)
        s.now += timedelta(minutes=12)
        s.tick(500)
        outs = [s.tick(3000 if k < 3 else 500) for k in range(40)]
        r["warmup_allowance"] = outs[7]["spike_allowance_w"] == 0          # the 9th sample: still warming up
        r["refill_allowance"] = max(o["spike_allowance_w"] for o in outs) <= KETTLE_PEAK + 1
        s = Sim(pkg, power=700, soc=60)
        warm(s, 12)
        s.tick(reported=False)
        s.tick(reported=False)
        s.replay_poll_text()
        r["replay"] = [s.tick(reported=False)["status"] for _ in range(3)][-1] == "stale"
    except Exception as exc:  # noqa: BLE001 - a mutant that crashes the templates is caught too
        r["crash"] = f"{type(exc).__name__}: {exc}"
    return r


baseline = scenario_suite(PKG)
check("the mutation battery holds on the real package", all(v is True for v in baseline.values()), str(baseline))
MUTANTS = [
    ("clipping removed (spikes pass straight into the usage)", "{%- set k = [4, (c - 1) // 2] | min -%}", "{%- set k = 0 -%}",
     "spike"),
    ("staleness ignored", "age is not none and age <= 180", "age is not none and age <= 999999", "stale"),
    ("charging shown as holding", "{%- set out.status = 'charging' -%}", "{%- set out.status = 'holding' -%}", "charging"),
    ("direction from a median-like run only (the N1 trap: cycling loads look idle)",
     "{%- elif usage >= 60 or (ns.direction == 'discharging' and usage >= 40) -%}", "{%- elif false -%}", "duty_cycle"),
    ("sustained idle run ignored (idle takes the whole window to show)", "{%- set ns.direction = run -%}",
     "{%- set ns.direction = ns.direction if ns.direction is not none else run -%}", "idle_fast"),
    ("a replayed poll text counts as fresh (the reconnect trap)", "(poll_valid and poll_text != prev_poll_text)", "(poll_valid)",
     "replay"),
    ("reserve hard-coded", "{%- set reserve = states(e_reserve) | float(none) -%}", "{%- set reserve = 20.0 -%}", "reserve"),
    ("warm-up removed", "ns.n >= 10 and last_ts", "ns.n >= 1 and last_ts", "warmup"),
    ("measured capacity never used", "ns.obs >= 3 -%}", "ns.obs >= 99999 -%}", "learning"),
    ("gap reset removed", "dt <= 0 or dt > 300 or jump", "dt <= 0 or dt > 999999 or jump", "gap"),
    ("holding shown as discharging", "{%- elif ns.direction != 'discharging' -%}", "{%- elif false -%}", "holding"),
    ("liveness from the battery power value only (the ESPHome trap)", "{%- if poll_valid and poll_seen_at is number -%}",
     "{%- if false -%}", "idle_fresh"),
    ("allowance learning while charging", "{%- if ns.added_dt is number and history_ok and ns.direction == 'discharging' -%}",
     "{%- if ns.added_dt is number -%}", "charge_allowance"),
    ("reserve comparison off by one", "{%- elif soc <= reserve -%}", "{%- elif soc < reserve -%}", "at_reserve"),
    ("allowance learning during the warm-up", "{%- if ns.added_dt is number and history_ok and ns.direction == 'discharging' -%}",
     "{%- if ns.added_dt is number and ns.direction == 'discharging' -%}", "warmup_allowance"),
    ("clipped energy averaged over the samples present (a kettle over-counted while the window refills)",
     "/ 30) if (wn > 0 and wk > 0)", "/ wn) if (wn > 0 and wk > 0)", "refill_allowance"),
]
for name, anchor, repl, key in MUTANTS:
    n = PKG_TEXT.count(anchor)
    if n != 1:
        check(f"mutant '{name}': its anchor occurs exactly once", False, f"{n}x: {anchor[:60]}")
        continue
    res = scenario_suite(Package(PKG_TEXT.replace(anchor, repl), sandboxed=True))
    check(f"mutant '{name}' is caught by the '{key}' scenario", res.get(key) is not True or "crash" in res, str(res))
CONTROLS = [
    ("equivalent: the clip count written with a filter", "{%- set k = [4, (c - 1) // 2] | min -%}",
     "{%- set k = [4, ((c - 1) / 2) | int] | min -%}"),
    ("equivalent: the usage threshold written as a float", "{%- elif usage >= 60 or (ns.direction == 'discharging' and usage >= 40) -%}",
     "{%- elif usage >= 60.0 or (ns.direction == 'discharging' and usage >= 40.0) -%}"),
]
for name, anchor, repl in CONTROLS:
    res = scenario_suite(Package(PKG_TEXT.replace(anchor, repl, 1), sandboxed=True))
    check(f"control '{name}' survives the battery", all(v is True for v in res.values()), str(res))

# ===========================================================================
print("")
print("[15] the post-export declaration (PEX entry fe1)")
# ===========================================================================
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _fe1_scope as F  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: the files as of the entry before fe1, undone exactly; this suite pins fe1's declaration)

FE1_FINGERPRINT = "211221b095bcdb61b2e7a2cfdd38fb28c871319d46d9acaf6e4f315a690de57e"
# The eight post-export fingerprints recorded on main before fe1, in chain order (pex0 first); none may be rewritten.
OLDER_FINGERPRINTS = (
    "c91d3a5834cef6b69f692bd8c301a478138ac7627b29c53a0a0e35cac29b36f8",
    "313f73eadd0c104cd1e81f35690fac52e0b065b0eef3eed35c9718f965baeb6c",
    "46cf76256da78b24e2fd59692f0bf126eba059352c37006542708c64b38e8f8c",
    "02d4bf53955acc3788c9df5972327bb62d5af028d8b9e46e0aa872c4fc94b0a0",
    "ee161454359816ee40e44c04dd0c009d0b96838ba912bcf606975bcb0049d528",
    "462f44d25c0c5dc7aa9df86c8865f6474b56193d80553804daaf3e3ff34feb5d",
    "43331ffff6819253b6106e1af9056253aa5105cec3b77be0a2c3b6ccf9554286",
    "1a56962c110b98a28537a649998b40f9c2635176de756ac505eda0513a972f3a",
)
BEFORE = {   # sha256 (LF) as of ovw1: the newest declared states fe1 starts from
    F.DASHBOARD_REL: "8f0da9f9ed3597e3128325b04cd54ca11698512d7f52c6d9598ec1ff26ac5c2e",
    F.VERSION_REL: "04b7b66b85688f7a40ab0d893505de65e45a0d283a93eae80c3fcdab4aad9c7a",
    F.MANIFEST_REL: "694f4a71b1f72089f64912c41e32d739ab9aaf3089e1c9785905b8c9dc6963c2",
}


def at_ovw1(rel: str) -> str:
    return _pex.as_of(rel, "ovw1", _pex.read(rel))   # PEX: fe1 (and any later entry) undone exactly, sha256-checked at each step


FE1 = sc.CHAIN.entry("fe1")
post = list(sc.POST_EXPORT_ENTRIES)
ids = [e.id for e in post]
check("fe1 is the ninth post-export entry, appended right after ovw1 (pex0 is the first)",
      "fe1" in ids and ids.index("fe1") == 8 and sc.CHAIN.prev_id("fe1") == "ovw1" and ids[0] == "pex0", str(ids))
check("fe1 declares exactly the manifest as chain-pinned and exactly the dashboard and VERSION.yaml as frozen, each with its reverter "
      "and checkpoint, and no delta, op path, include, substitution, banned token or tag",
      set(FE1.reverts) == set(FE1.checkpoints) == {sc.HA_MANIFEST} == set(F.PINNED_REVERTERS)
      and set(FE1.frozen_reverts) == set(FE1.frozen_checkpoints) == {F.DASHBOARD_REL, F.VERSION_REL} == set(F.FROZEN_REVERTERS)
      and not FE1.deltas and not FE1.op_paths_changed and not FE1.includes_added and not FE1.subst_added
      and not FE1.subst_changed and not FE1.subst_removed and not FE1.banned_fw_added and not FE1.banned_files
      and not FE1.tags_declared and not FE1.tags_promoted)
check("fe1 declares the five files it adds (the package, this suite, the card's FE-1 tests, the documentation page, its scope module) "
      "and each exists", FE1.added_files == F.ADDED_FILES and len(F.ADDED_FILES) == 5 and PKG_REL in F.ADDED_FILES
      and all((ROOT / f).is_file() for f in FE1.added_files))
CARD_FILES_CHANGED = ("frontend/ecco-energy-flow-card/src/ecco-energy-flow-card.ts", "frontend/ecco-energy-flow-card/src/utils/display.ts",
                      "frontend/ecco-energy-flow-card/src/utils/format.ts", "frontend/ecco-energy-flow-card/README.md",
                      "frontend/ecco-energy-flow-card/dist/ecco-energy-flow-card.js",
                      "frontend/ecco-energy-flow-card/examples/generic-example.yaml")
check("no file is enrolled for fe1: none of the Energy Flow card files FE-1 changes is frozen (its frozen DESIGN.md and "
      "examples/ecco-example.yaml are untouched), and ENROLLED stays at six files",
      len(_pex.ENROLLED) == 6 and not set(CARD_FILES_CHANGED) & _pex.FROZEN
      and {"frontend/ecco-energy-flow-card/DESIGN.md", "frontend/ecco-energy-flow-card/examples/ecco-example.yaml"} <= _pex.FROZEN)
check("fe1's fingerprint is the pinned value, linked to ovw1's; every older post-export fingerprint is its recorded value",
      FE1.fingerprint == FE1_FINGERPRINT == _pex.fingerprint(FE1) and _pex.record(FE1)["parent"] == OLDER_FINGERPRINTS[-1]   # PEX: hash link
      and tuple(e.fingerprint for e in post[:8]) == OLDER_FINGERPRINTS)
old = {rel: at_ovw1(rel) for rel in BEFORE}
check("undone exactly, the dashboard, VERSION.yaml and the manifest are their ovw1 state byte for byte (sha256)",
      all(F.sha(old[rel]) == h for rel, h in BEFORE.items()), str({r: F.sha(t)[:16] for r, t in old.items()}))
check("...in which nothing of FE-1 exists (no time_to_reserve, no package stanza, dashboard 7.20.0)",
      "time_to_reserve" not in old[F.DASHBOARD_REL] and PKG_REL not in old[F.MANIFEST_REL]
      and 'version: "7.20.0"' in old[F.VERSION_REL]
      and 'version: "7.21.0"' in (ROOT / "VERSION.yaml").read_text(encoding="utf-8"))
check("each fe1 pair round-trips (applying it to the ovw1 text gives the live file)",
      F.add_fe1_dashboard(old[F.DASHBOARD_REL]) == (ROOT / "home-assistant" / "dashboards" / "ecco_pro.yaml").read_text(encoding="utf-8")
      and F.add_fe1_version(old[F.VERSION_REL]) == (ROOT / "VERSION.yaml").read_text(encoding="utf-8")
      and F.add_fe1_manifest(old[F.MANIFEST_REL]) == (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8"))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All FE-1 battery time-to-reserve checks passed.")
print("These prove the package's templates offline (behaviour, boundaries, oracle agreement, wiring, mutations); they prove "
      "nothing about a live Home Assistant, the inverter or the batteries.")
