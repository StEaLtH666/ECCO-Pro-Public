#!/usr/bin/env python3
"""hd1 derived house load (home-assistant/packages/ecco_canonical_telemetry.yaml): offline proofs.

The package's REAL Jinja templates (the trigger-based ECCO House Power Model and the state-based ECCO House Power that
presents it) are rendered with stand-ins for the Home Assistant template functions they use (states() / states[...] /
is_state / state_attr / now / as_timestamp / this / trigger, and HA's forgiving float filter that RAISES without a default),
in BOTH a plain and an immutable sandboxed Jinja environment (Home Assistant renders in a sandbox). The model attribute
round-trips through ast.literal_eval, as Home Assistant parses a rendered attribute. Inputs behave like ESPHome: an unchanged
value never reaches the state machine, and a dongle poll publishes its readings, then (only after a complete poll, and only
while it has NTP time) its last_telemetry_update text.

  [0] static: template only (no action / service / script / automation / esphome call), the triggers, the two entities and
      their Home Assistant semantics (unique_id, W, power, measurement), every input entity exists in the firmware
  [1] accurate native consumption is used as it is
  [2] the native load's false 0 W during export: inverter + grid CT (the A8 measurements)
  [3] import / export sign changes, grid charging (inverter AC negative)
  [4] battery charging and discharging, solar generation, idle and near-zero loads
  [5] sensor dropout: native, inverter or grid unavailable / garbage; a 0 W that cannot be confirmed is never a value
  [6] stale telemetry: no complete poll, the offline flag, a reconnect replaying an old poll text, recovery; no NTP time
  [7] telemetry timestamp inconsistencies: a half-published poll never mixes two polls
  [8] Home Assistant restart and template reload
  [9] parity with the Energy Flow card's resolveHomeW() vectors (frontend/ecco-energy-flow-card/test/homePower.test.ts)
  [10] the presentation sensor: unavailable (never 0 W) unless fresh and the model is updating; attributes
  [11] consumers: the snapshot, the learning gate, the dashboard (16 reads; the register table keeps register 178), the
       Battery Outlook learning (0 W samples excluded, nothing rewritten), FE-1 and the Energy Flow card unchanged
  [12] mutation: each named mutant of the package is caught
  [13] the post-export declaration (PEX entry hd1)

Test-only. No Home Assistant, no network, no hardware. I/O: reads repo files.
"""

from __future__ import annotations

import ast
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jinja2
import jinja2.sandbox
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
PKG_REL = "home-assistant/packages/ecco_canonical_telemetry.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
FIRMWARE = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")

E_NATIVE = "sensor.ecco_clock_dongle_ecco_load_power"
E_INV = "sensor.ecco_clock_dongle_ecco_inverter_output_power"
E_GRID = "sensor.ecco_clock_dongle_ecco_grid_power_ct_clamp"
E_ONLINE = "binary_sensor.ecco_clock_dongle_telemetry_online"
E_POLLED = "sensor.ecco_clock_dongle_last_telemetry_update"
E_MODEL = "sensor.ecco_house_power_model"
E_HOUSE = "sensor.ecco_house_power"
T0 = datetime(2026, 10, 15, 19, 48, 0, tzinfo=timezone.utc)

FAILURES: list[str] = []
PASSES = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSES
    if condition:
        PASSES += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f"\n        {detail}" if detail else ""))


_MISSING = object()


def ha_float(value, default=_MISSING):
    """homeassistant.helpers.template.forgiving_float_filter: a default is required for a non-number."""
    try:
        return float(value)
    except (ValueError, TypeError):
        if default is _MISSING:
            raise ValueError(f"float got invalid input {value!r} and no default") from None
        return default


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
    def __init__(self, entity_id, state, last_changed, last_updated, last_reported, attributes):
        self.entity_id = entity_id
        self.state = state
        self.last_changed = last_changed
        self.last_updated = last_updated
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
        return StateObj(entity_id, e["state"], e["t"], e["t"], e["t"], {})


class This:
    def __init__(self, state, attributes):
        self.state = state
        self.attributes = attributes


def make_env(sandboxed: bool) -> jinja2.Environment:
    cls = jinja2.sandbox.ImmutableSandboxedEnvironment if sandboxed else jinja2.Environment
    env = cls(undefined=jinja2.StrictUndefined)
    env.filters["float"] = ha_float
    return env


def parse_result(text: str):
    s = text.strip()
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return s


class Package:
    """The hd1 templates of the canonical package, compiled in one environment."""

    def __init__(self, text: str, sandboxed: bool):
        data = yaml.safe_load(text)
        blocks = data["template"]
        model_blocks = [b for b in blocks if any(s.get("unique_id") == "ecco_house_power_model" for s in b.get("sensor", []))]
        house_blocks = [b for b in blocks if any(s.get("unique_id") == "ecco_house_power" for s in b.get("sensor", []))]
        assert len(model_blocks) == 1 and len(house_blocks) == 1, "expected one model block and one house block"
        self.model_block, self.house_block = model_blocks[0], house_blocks[0]
        self.triggers = self.model_block.get("triggers")
        model = [s for s in self.model_block["sensor"] if s["unique_id"] == "ecco_house_power_model"][0]
        house = [s for s in self.house_block["sensor"] if s["unique_id"] == "ecco_house_power"][0]
        self.model_cfg, self.house_cfg = model, house
        env = make_env(sandboxed)
        self.model_state = env.from_string(model["state"])
        self.model_attr = env.from_string(model["attributes"]["model"])
        self.house_avail = env.from_string(house["availability"])
        self.house_state = env.from_string(house["state"])
        self.house_attrs = {k: env.from_string(v) for k, v in house["attributes"].items() if isinstance(v, str) and "{{" in v}


def poll_text(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


class Sim:
    """One Home Assistant instance: the dongle's entities, the clock, the model entity and the presentation sensor."""

    def __init__(self, pkg: Package, native=1350, inv=1334, grid=16, online="on", start=T0, ntp=True, started=True):
        self.pkg = pkg
        self.now = start
        self.ntp = ntp
        self.ent: dict = {}
        self.model = None
        self.model_state = "unknown"
        self.fired: list[str] = []
        self._set(E_ONLINE, online, fire=False)
        self._set(E_NATIVE, native, fire=False)
        self._set(E_INV, inv, fire=False)
        self._set(E_GRID, grid, fire=False)
        self._set(E_POLLED, poll_text(self.now) if ntp else "Waiting", fire=False)
        if started:
            self.fire("start")

    # ---- inputs ----------------------------------------------------------------------------------------------------------
    def _set(self, eid, value, fire=True):
        """ESPHome: an UNCHANGED value never reaches the state machine (no timestamps move, no trigger fires)."""
        v = value if isinstance(value, str) else (str(float(value)) if isinstance(value, (int, float)) else str(value))
        e = self.ent.get(eid)
        if e is not None and e["state"] == v:
            return
        self.ent[eid] = {"state": v, "t": self.now}
        if fire:
            tid = {E_POLLED: "poll", E_ONLINE: "liveness"}.get(eid, "input")
            self.fire(tid)

    def poll(self, native=None, inv=None, grid=None, ok=True, partial=None):
        """One dongle poll: the readings that changed, then the online flag, then (complete poll, NTP time) the poll text.
        `partial` = publish only those readings (a half-published poll: the rest and the poll text not yet)."""
        if not ok:
            self._set(E_ONLINE, "off")
            return
        vals = [(E_NATIVE, native), (E_INV, inv), (E_GRID, grid)]
        for eid, v in vals:
            if v is not None and (partial is None or eid in partial):
                self._set(eid, v)
        if partial is not None:
            return
        self._set(E_ONLINE, "on")
        if self.ntp:
            self._set(E_POLLED, poll_text(self.now))

    def advance(self, seconds: float):
        """Advance the clock, firing the 10-second time pattern on every boundary passed."""
        end = self.now + timedelta(seconds=seconds)
        nxt = (self.now.replace(microsecond=0) + timedelta(seconds=10 - self.now.second % 10))
        while nxt <= end:
            self.now = nxt
            self.fire("tick")
            nxt += timedelta(seconds=10)
        self.now = end

    def step(self, native=None, inv=None, grid=None, seconds=10, **kw):
        """10 s pass, then a poll."""
        self.advance(seconds)
        self.poll(native, inv, grid, **kw)
        return self.presented()

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
            "trigger": {"id": trigger_id},
        }

    def fire(self, trigger_id):
        ctx = self._ctx(trigger_id)
        out = parse_result(self.pkg.model_attr.render(ctx))
        if not isinstance(out, dict):
            raise AssertionError(f"model attribute did not parse to a mapping: {str(out)[:200]}")
        self.model_state = self.pkg.model_state.render(ctx)
        self.model = out
        self.fired.append(trigger_id)
        return out

    def presented(self):
        """The presentation sensor now: (available, state, attributes)."""
        ctx = self._ctx("none")
        avail = parse_result(self.pkg.house_avail.render(ctx)) is True
        state = parse_result(self.pkg.house_state.render(ctx))
        attrs = {k: parse_result(t.render(ctx)) for k, t in self.pkg.house_attrs.items()}
        return avail, state, attrs

    def value(self):
        """What Home Assistant shows: the number, or None when unavailable."""
        avail, state, _ = self.presented()
        return state if avail and isinstance(state, (int, float)) else None

    def restart(self, gap_s=30):
        """Home Assistant goes down for gap_s and comes back: the model attribute is RESTORED (trigger-based template), the
        dongle's entities are as the integration finds them, the start trigger fires."""
        self.now += timedelta(seconds=gap_s)
        self.fire("start")


PKGS = {"plain": Package(PKG_TEXT, sandboxed=False), "sandbox": Package(PKG_TEXT, sandboxed=True)}
PKG = PKGS["sandbox"]


def near(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


# ===========================================================================================================================
print("[0] static")
# ===========================================================================================================================
pkg_yaml = yaml.safe_load(PKG_TEXT)
check("the package is template only (no action / service / script / automation / esphome call)",
      set(pkg_yaml) == {"template"} and not re.search(r"\b(action|service):|esphome\.|script\.|automation", PKG_TEXT))
trig = {(t.get("trigger"), t.get("id")) for t in PKG.triggers}
check("the model's triggers: the poll text (poll), the three readings (input), the online flag (liveness), every 10 s (tick), "
      "start", trig == {("state", "poll"), ("state", "input"), ("state", "liveness"), ("time_pattern", "tick"),
                        ("homeassistant", "start")}
      and [t for t in PKG.triggers if t.get("id") == "tick"][0].get("seconds") == "/10"
      and sorted([t for t in PKG.triggers if t.get("id") == "input"][0]["entity_id"]) == sorted([E_NATIVE, E_INV, E_GRID])
      and [t for t in PKG.triggers if t.get("id") == "poll"][0]["entity_id"] == E_POLLED, str(trig))
h = PKG.house_cfg
check("ECCO House Power keeps its Home Assistant semantics: unique_id ecco_house_power, W, power, measurement (statistics "
      "continue), and is a lookup of the model only", h["unique_id"] == "ecco_house_power" and h["unit_of_measurement"] == "W"
      and h["device_class"] == "power" and h["state_class"] == "measurement" and "triggers" not in PKG.house_block
      and "ecco_clock_dongle" not in yaml.safe_dump(h))
fw_names = set(re.findall(r'name: "([^"]+)"', FIRMWARE))
slugs = {re.sub(r"[^a-z0-9]+", "_", n.lower()).strip("_") for n in fw_names}
used = sorted({e.split(".", 1)[1].replace("ecco_clock_dongle_", "") for e in (E_NATIVE, E_INV, E_GRID, E_ONLINE, E_POLLED)})
check("every dongle entity the model reads is a firmware entity (load power, inverter output power, grid CT, telemetry online, "
      "last telemetry update)", set(used) <= slugs, str(sorted(set(used) - slugs)))
check("the unique_id is defined once in the repository's packages",
      sum(p.read_text(encoding="utf-8").count("unique_id: ecco_house_power\n") for p in (ROOT / "home-assistant" / "packages").glob("*.yaml")) == 1)

# ===========================================================================================================================
print("\n[1] accurate native consumption")
# ===========================================================================================================================
for name, pkg in PKGS.items():
    s = Sim(pkg)
    s.step(1350, 1334, 16)
    av, st, at = s.presented()
    check(f"[{name}] native 1350 W with inverter 1334 W and grid +16 W: 1350 W from the native load", av and st == 1350.0
          and at["source"] == "native" and at["derived_w"] == 1350.0, f"{av} {st} {at}")
s = Sim(PKG)
s.step(980, 400, 560)
check("a native reading that differs from inverter + grid is still preferred when non-zero (credible native first)",
      s.value() == 980.0 and s.presented()[2]["source"] == "native", str(s.presented()))

# ===========================================================================================================================
print("\n[2] the native load's false 0 W during export (A8, 15 Oct)")
# ===========================================================================================================================
s = Sim(PKG)
rows = [(0, 2000, -667, 1333.0), (0, 2000, -726, 1274.0), (0, 2002, -755, 1247.0), (0, 3001, -1772, 1229.0), (0, 2999, -1764, 1235.0)]
got = []
for n, i, g, want in rows:
    s.step(n, i, g)
    got.append((s.value(), want, s.presented()[2]["source"]))
check("native 0 W while exporting (inverter 2000-3000 W, grid -667..-1772 W): inverter + grid, 1229-1333 W, source derived",
      all(near(v, w) and src == "derived" for v, w, src in got), str(got))

# ===========================================================================================================================
print("\n[3] import / export sign changes and grid charging")
# ===========================================================================================================================
s = Sim(PKG)
seq = [(1300, 1250, 50, 1300.0), (0, 2500, -1200, 1300.0), (1310, 1300, 10, 1310.0), (0, -6785, 8149, 1364.0),
       (0, -6910, 8288, 1378.0), (1290, -6900, 8190, 1290.0), (0, 1800, -500, 1300.0)]
out = []
for n, i, g, want in seq:
    s.step(n, i, g)
    out.append((s.value(), want))
check("import -> export -> import -> grid charging (inverter -6785 W, grid +8149 W: 1364 W, 11 Oct) -> export: every step right",
      all(near(v, w) for v, w in out), str(out))
s = Sim(PKG)
s.step("unavailable", 400, -600)
check("native unavailable and inverter + grid below 0 (a reading glitch): clamps to 0 W, never negative",
      s.value() == 0.0, str(s.presented()))

# ===========================================================================================================================
print("\n[4] battery, solar, idle and near-zero loads")
# ===========================================================================================================================
s = Sim(PKG)
cases = [((0, 2500, -1200), 1300.0, "solar day: inverter 2500 W (PV 4 kW, battery charging), export 1200 W"),
         ((0, 3200, -1900), 1300.0, "battery discharging to export (Dump to Grid)"),
         ((0, -2500, 3800), 1300.0, "battery charging from the grid"),
         ((300, 280, 20), 300.0, "idle night, native credible"),
         ((0, 50, 30), 0.0, "native 0 W confirmed: inverter + grid only 80 W (at or below the 150 W margin)"),
         ((0, 100, 50), 0.0, "exactly at the 150 W margin: the native 0 W stands (the card's and the firmware's rule)"),
         ((0, 100, 51), 151.0, "1 W past the margin: inverter + grid")]
res = []
for (n, i, g), want, label in cases:
    s.step(n, i, g)
    res.append((label, s.value(), want))
for label, v, want in res:
    check(label + f": {want} W", near(v, want), str(v))

# ===========================================================================================================================
print("\n[5] sensor dropout and garbage")
# ===========================================================================================================================
s = Sim(PKG)
s.step("unavailable", 2000, -700)
check("native unavailable, inverter + grid fine: 1300 W derived", near(s.value(), 1300.0)
      and s.presented()[2]["source"] == "derived", str(s.presented()))
s.step("unavailable", "unavailable", -700)
check("native and inverter unavailable: UNAVAILABLE (never 0 W)", s.value() is None and s.presented()[0] is False,
      str(s.presented()))
s.step(0, "unavailable", -700)
check("native 0 W with the inverter unavailable: UNAVAILABLE - a 0 W that inverter + grid cannot confirm is not a value",
      s.value() is None and "cannot be confirmed" in s.model["reason"], str(s.model))
s.step(0, 2000, "unknown")
check("native 0 W with the grid CT unknown: UNAVAILABLE", s.value() is None, str(s.presented()))
s.step("nan", 2000, -700)
check("native 'nan': treated as unavailable, inverter + grid used", near(s.value(), 1300.0), str(s.presented()))
s.step(40000, 2000, -700)
check("native out of range (40000 W): treated as unavailable, inverter + grid used", near(s.value(), 1300.0), str(s.presented()))
s.step(-250, 100, 50)
check("a negative native reading clamps to 0 W", s.value() == 0.0, str(s.presented()))
s.step(1200, 2000, -700)
check("recovery: native credible again", s.value() == 1200.0, str(s.presented()))

# ===========================================================================================================================
print("\n[6] stale telemetry")
# ===========================================================================================================================
s = Sim(PKG)
s.step(1200, 1180, 20)
s.advance(55)
check("55 s after the last complete poll: still current", s.value() == 1200.0)
s.advance(15)
check("70 s after the last complete poll (no poll since; the 60 s limit is checked every 10 s): UNAVAILABLE, never the old "
      "value or 0 W", s.value() is None
      and s.model["fresh"] is False, str(s.model))
s.step(1210, 1190, 20)
check("a new complete poll: current again", s.value() == 1210.0)
s.poll(ok=False)
check("the dongle reports telemetry offline: UNAVAILABLE at once", s.value() is None)
s.step(1220, 1200, 20)
check("telemetry back online with a new poll: current", s.value() == 1220.0)
s.advance(120)
s.ent[E_POLLED]["t"] = s.now                              # an API reconnect: HA writes the cached poll text again
s.fire("poll")
check("a reconnect that replays the OLD poll text does not count as a poll: still UNAVAILABLE", s.value() is None,
      str(s.model))
s = Sim(PKG, ntp=False)
s.step(1200, 1180, 20)
check("no NTP time yet (poll text 'Waiting'): the newest report of the readings is the liveness fallback - current",
      s.value() == 1200.0, str(s.model))
s.advance(70)
check("...and with readings unchanged for 70 s it is UNAVAILABLE rather than trusted", s.value() is None)
s.step(1300, 1250, 50)
check("...a changed reading makes it current again", s.value() == 1300.0)

# ===========================================================================================================================
print("\n[7] telemetry timestamp inconsistencies")
# ===========================================================================================================================
s = Sim(PKG)
s.step(0, 2000, -700)
before = s.value()
s.advance(10)
s.poll(inv=-6800, partial={E_INV})                           # half a poll: the inverter is new, the grid and poll text not yet
mid = s.value()
s.fire("tick")
mid_tick = s.value()
s.poll(0, -6800, 8100)
after = s.value()
check("a half-published poll (charging inverter -6800 W next to the old export grid -700 W) never mixes two polls: the value is "
      "held until the poll is complete, then recomputed (1300 W)", before == 1300.0 and mid == 1300.0 and mid_tick == 1300.0
      and near(after, 1300.0), f"{before} {mid} {mid_tick} {after}")
check("...the mixed reading (-6800 + -700 = 0 W) is never shown", 0.0 not in (mid, mid_tick))
s = Sim(PKG)
s.step(1200, 1180, 20)
s.ent[E_POLLED]["state"] = "2026-10-15 19:40:00"            # the dongle's clock stepped back (a new, older-looking text)
s.ent[E_POLLED]["t"] = s.now
s.fire("poll")
check("a poll text that steps backwards is still a NEW poll as seen here (liveness is when Home Assistant saw it change)",
      s.value() == 1200.0 and s.model["fresh"] is True)

# ===========================================================================================================================
print("\n[8] restart and reload")
# ===========================================================================================================================
s = Sim(PKG)
s.step(0, 2000, -700)
s.restart(gap_s=20)
check("a short restart (20 s) with the last complete poll seen 20 s ago: still current, recomputed at start (1300 W)",
      near(s.value(), 1300.0), str(s.model))
s = Sim(PKG)
s.step(0, 2000, -700)
s.restart(gap_s=90)
check("a 90 s restart with the dongle's last poll text unchanged: UNAVAILABLE until a NEW poll (the restored memory remembers "
      "that text, so it is not mistaken for a new one)", s.value() is None, str(s.model))
s.step(0, 2000, -650)
check("...the first new poll after the restart: current (1350 W)", near(s.value(), 1350.0))
s2 = Sim(PKG, started=False)
s2.model = None
s2.fire("start")
check("a first install (no memory at all): the poll text the integration has just published counts as seen now (ESPHome "
      "entities are not restored across a restart, so it comes from a live publish)", s2.value() == 1350.0, str(s2.model))
s2.step(1100, 1080, 20)
check("...and the next poll is used", s2.value() == 1100.0)
s3 = Sim(PKG)
s3.step(1100, 1080, 20)
s3.model = parse_result(str(s3.model))                        # a template reload: the attribute round-trips through its text form
s3.fire("start")
check("a template reload right after a poll keeps the value current (the poll text was seen 0 s ago)", s3.value() == 1100.0)

# ===========================================================================================================================
print("\n[9] parity with the Energy Flow card's resolveHomeW() (homePower.test.ts)")
# ===========================================================================================================================
CARD_TEST = (ROOT / "frontend/ecco-energy-flow-card/test/homePower.test.ts").read_text(encoding="utf-8")
CARD_SRC = (ROOT / "frontend/ecco-energy-flow-card/src/config.ts").read_text(encoding="utf-8")
VECTORS = [((1200, 1000, 500), 1200.0), ((None, 1240, 1810), 3050.0), ((0, 3030, 20), 3050.0), ((0, 0, 0), 0.0),
           ((0, 10, -5), 0.0), ((0, 100, 50), 0.0), ((0, 100, 51), 151.0), ((-30, 10, 10), 0.0), ((3050, 3030, 210), 3050.0)]
mism = []
for (n, i, g), want in VECTORS:
    s = Sim(PKG)
    s.step("unavailable" if n is None else n, i, g)
    if not near(s.value(), want):
        mism.append(((n, i, g), s.value(), want))
check("the card's resolveHomeW vectors give the same house load here (native, the derived fallback, the 150 W margin, the "
      "clamp)", not mism and "export const HOME_FALLBACK_MIN_W = 150;" in CARD_SRC and "resolveHomeW" in CARD_TEST, str(mism))
s = Sim(PKG)
s.step(0, "unavailable", "unavailable")
check("the one deliberate difference: native 0 W with inverter and grid unavailable is UNAVAILABLE here (the card shows "
      "0 W); a canonical sensor that feeds statistics never records an unconfirmed zero", s.value() is None)

# ===========================================================================================================================
print("\n[10] the presentation sensor")
# ===========================================================================================================================
s = Sim(PKG)
s.step(0, 2000, -700)
av, st, at = s.presented()
check("attributes: source, reason, native / inverter / grid / derived W, telemetry age, refreshed_at, the model as source_entity",
      av and at["source"] == "derived" and at["native_w"] == 0.0 and at["inverter_w"] == 2000.0 and at["grid_w"] == -700.0
      and at["derived_w"] == 1300.0 and isinstance(at["telemetry_age_s"], (int, float)) and at["refreshed_at"]
      and PKG.house_cfg["attributes"]["source_entity"] == E_MODEL, str(at))
s.model = dict(s.model, evaluated_at=(s.now - timedelta(seconds=90)).isoformat())
check("a model that stops updating (evaluated 90 s ago) is not shown as current: UNAVAILABLE", s.value() is None)
s = Sim(PKG)
s.model = None
check("no model at all: UNAVAILABLE, attributes say so", s.value() is None and s.presented()[2]["source"] == "none")
vals = []
s = Sim(PKG)
for k in range(60):
    s.step(0 if k % 3 else 900 + k, 1500 + 10 * k, -400 - 7 * k)
    v = s.value()
    vals.append(v)
check("over a mixed run every shown value is a number >= 0 W with one decimal", all(isinstance(v, float) and v >= 0
      and round(v, 1) == v for v in vals), str(vals[:6]))

# ===========================================================================================================================
print("\n[11] consumers")
# ===========================================================================================================================
CORE = (ROOT / "home-assistant/packages/ecco_pro.yaml").read_text(encoding="utf-8")
DASH = (ROOT / "home-assistant/dashboards/ecco_pro.yaml").read_text(encoding="utf-8")
FLUX = (ROOT / "influxdb/tasks/ecco_battery_outlook_5m.flux").read_text(encoding="utf-8")
FE1 = (ROOT / "home-assistant/packages/ecco_battery_runtime.yaml").read_text(encoding="utf-8")
snap = CORE.split("unique_id: ecco_house_load_snapshot", 1)[1].split("- name:", 1)[0]
gate = CORE.split("unique_id: ecco_model_inputs_ready", 1)[1].split("- name:", 1)[0]
check("the House Load Snapshot and the Model Inputs Ready learning gate read the canonical house load, not the native load",
      "sensor.ecco_house_power" in snap and "ecco_load_power" not in snap and "sensor.ecco_house_power" in gate
      and "ecco_load_power" not in gate)
raw = [l.strip()[:70] for l in DASH.splitlines() if re.search(r"sensor\.ecco_clock_dongle_ecco_load_power(?![a-z0-9_])", l)]
check("the dashboard reads the native load in exactly one place: the Inverter / Advanced register table (register 178 itself)",
      len(raw) == 1 and "Power L1 / L2 / Total" in raw[0], str(raw))
canon = len(re.findall(r"sensor\.ecco_house_power(?![a-z0-9_])", DASH))
check("...and the canonical house load in 17 (the 16 moved house-load reads: Today / Smart Charge status and runtime blends, the "
      "not-reporting lists, the three House chart series, the Live Energy Flow essential power; plus the Energy Flow card)",
      canon == 17, str(canon))
learn = FLUX.split("loadHistory =", 1)[1].split("trainingRecord", 1)[0]
check("the Battery Outlook learning keeps canonical-first / legacy-fill, and excludes 5-minute house samples of 0 W or less "
      "(no history rewrite: a filter in the read only)", 'canonicalMeasurement: "sensor.ecco_house_power"' in learn
      and 'legacyMeasurement: "sensor.ecco_clock_dongle_ecco_load_power"' in learn
      and "|> filter(fn: (r) => r._value > 0.0)" in learn and FLUX.count("r._value > 0.0") == 1)
check("FE-1 (battery time to reserve) reads no house load: it is unaffected", "house" not in FE1.lower().replace("household", "")
      and "load_power" not in FE1)
check("the Energy Flow card still resolves its home node itself (resolveHomeW unchanged) and reads the canonical house load",
      "export function resolveHomeW(nativeW: number | null, inverterW: number | null, gridW: number | null): number | null" in CARD_SRC
      and "power: sensor.ecco_house_power" in DASH)

# ===========================================================================================================================
print("\n[12] mutation")
# ===========================================================================================================================


def battery(text: str) -> dict:
    res = {}
    try:
        p = Package(text, sandboxed=True)
        s = Sim(p)
        s.step(0, 2000, -700)
        res["export"] = near(s.value(), 1300.0)
        s = Sim(p)
        s.step(0, 100, 51)
        res["margin"] = near(s.value(), 151.0)
        s = Sim(p)
        s.step(0, 100, 50)
        res["margin_eq"] = s.value() == 0.0
        s = Sim(p)
        s.step(0, "unavailable", -700)
        res["unconfirmed"] = s.value() is None
        s = Sim(p)
        s.step(1200, 1180, 20)
        s.advance(70)
        res["stale"] = s.value() is None
        s = Sim(p)
        s.step(1220, 1200, 20)
        s.advance(120)
        s.ent[E_POLLED]["t"] = s.now
        s.fire("poll")
        res["replay"] = s.value() is None
        s = Sim(p)
        s.step(0, 2000, -700)
        s.advance(10)
        s.poll(inv=-6800, partial={E_INV})
        res["mix"] = s.value() == 1300.0
        s = Sim(p)
        s.step(0, -6785, 8149)
        res["charging"] = near(s.value(), 1364.0)
        s = Sim(p)
        s.step("unavailable", 400, -600)
        res["clamp"] = s.value() == 0.0
        s = Sim(p)
        s.step(1200, 1180, 20)
        s.poll(ok=False)
        res["offline"] = s.value() is None
    except Exception as exc:  # noqa: BLE001
        res["crash"] = f"{type(exc).__name__}: {exc}"
    return res


base = battery(PKG_TEXT)
check("the mutation battery holds on the real package", all(v is True for v in base.values()), str(base))
MUTANTS = [
    ("the 150 W margin dropped (any derived value replaces a native 0 W)", "and d > 150 -%}", "and d > 0 -%}", "margin_eq"),
    ("the margin made >= (150 W itself replaces it)", "and d > 150 -%}", "and d >= 150 -%}", "margin_eq"),
    ("the derived fallback dropped for a native 0 W", "{%- elif n == 0 and d_ok and d > 150 -%}", "{%- elif false -%}", "export"),
    ("an unconfirmable native 0 W shown as 0 W", "{%- set r.v = none -%}{%- set r.src = 'none' -%}{%- set r.why = 'native 0 W cannot",
     "{%- set r.v = 0.0 -%}{%- set r.src = 'none' -%}{%- set r.why = 'native 0 W cannot", "unconfirmed"),
    ("freshness ignored", "{%- set fresh = online and age is not none and age >= -5 and age <= 60 -%}", "{%- set fresh = true -%}",
     "stale"),
    ("a replayed poll text counted as a poll", "{%- set new_poll = poll_valid and poll_text != pm.get('poll_text') -%}",
     "{%- set new_poll = poll_valid -%}", "replay"),
    ("recomputed on any input (mixing two polls)", "{%- set recompute = new_poll or tid == 'start' or not poll_valid",
     "{%- set recompute = true or new_poll or tid == 'start' or not poll_valid", "mix"),
    ("the grid sign inverted (inverter - grid)", "{%- set d = ([0, i + g] | max) if d_ok else none -%}",
     "{%- set d = ([0, i - g] | max) if d_ok else none -%}", "charging"),
    ("the clamp at 0 dropped", "{%- set d = ([0, i + g] | max) if d_ok else none -%}", "{%- set d = (i + g) if d_ok else none -%}",
     "clamp"),
    ("the offline flag ignored", "{%- set online = is_state(e_online, 'on') -%}", "{%- set online = true -%}", "offline"),
    ("the presentation available without freshness", "{{ m is mapping and m.get('fresh') is sameas true and m.get('value_w') is number",
     "{{ m is mapping and m.get('value_w') is number", "stale"),
]
for name, a, b, key in MUTANTS:
    if PKG_TEXT.count(a) < 1:
        check(f"mutant '{name}': its anchor occurs", False, a[:60])
        continue
    res = battery(PKG_TEXT.replace(a, b))
    check(f"mutant '{name}' is caught by '{key}'", res.get(key) is not True or "crash" in res, str(res))

# ===========================================================================================================================
print("\n[13] the post-export declaration (PEX entry hd1)")
# ===========================================================================================================================
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite pins hd1's declaration)
import _hd1_scope as F  # noqa: E402

HD1_FINGERPRINT = "990ebacac54a396852aa73f152f966711c671fcb6513ae24565a61841b5c4736"
E = sc.CHAIN.entry("hd1")
ids = [x.id for x in sc.POST_EXPORT_ENTRIES]
FROZEN_FILES = {"home-assistant/packages/ecco_canonical_telemetry.yaml", "home-assistant/packages/ecco_pro.yaml",
                "home-assistant/dashboards/ecco_pro.yaml", "influxdb/tasks/ecco_battery_outlook_5m.flux",
                "registry/system_health_checks.yaml"}
check("hd1 is appended right after smr1", ids[-1] == "hd1" and sc.CHAIN.prev_id("hd1") == "smr1", str(ids[-4:]))
check("hd1 declares exactly its five frozen edits (each with its reverter and checkpoint), its added files, and nothing else "
      "(no chain-pinned edit, delta, op path, include, substitution, banned token or tag)",
      set(E.frozen_reverts) == set(E.frozen_checkpoints) == set(F.FROZEN_REVERTERS) == FROZEN_FILES
      and all(f in _pex.FROZEN for f in FROZEN_FILES)   # PEX: each really is frozen, so the edit is declared
      and not E.reverts and not E.checkpoints and not F.PINNED_REVERTERS and not E.deltas and not E.op_paths_changed
      and not E.includes_added and not E.subst_added and not E.subst_changed and not E.subst_removed and not E.banned_fw_added
      and not E.banned_files and not E.tags_declared and not E.tags_promoted
      and E.added_files == F.ADDED_FILES and all((ROOT / f).is_file() for f in E.added_files))
# PEX: hd1's own fingerprint and its hash link to smr1
check("hd1's fingerprint is the pinned value, linked to smr1's", E.fingerprint == HD1_FINGERPRINT == _pex.fingerprint(E)
      and _pex.record(E)["parent"] == sc.CHAIN.entry("smr1").fingerprint)   # PEX: hash link
# PEX: each frozen file as of fcc1 (hd1 undone exactly, sha256-checked), and the round trip
pre = {rel: _pex.as_of(rel, "fcc1", _pex.read(rel)) for rel in sorted(FROZEN_FILES)}   # PEX: frozen reverters
adders = {"home-assistant/packages/ecco_canonical_telemetry.yaml": F.add_hd1_canonical, "home-assistant/packages/ecco_pro.yaml": F.add_hd1_core,
          "home-assistant/dashboards/ecco_pro.yaml": F.add_hd1_dashboard, "influxdb/tasks/ecco_battery_outlook_5m.flux": F.add_hd1_outlook,
          "registry/system_health_checks.yaml": F.add_hd1_health}
check("undone exactly, each file is its fcc1 state with no trace of hd1, and re-applying hd1's pairs gives the live file",
      all("hd1" not in t for t in pre.values())
      and all(adders[rel](pre[rel]) == _pex.read(rel) for rel in FROZEN_FILES))   # PEX: round trip
added = [l for l in F.OUTLOOK_0_NEW.splitlines() if l not in F.OUTLOOK_0_OLD.splitlines()]
check("the learning task's only change is comment lines and the one 0 W filter (the read, the profile and the write are as before)",
      bool(added) and all(l.startswith("//") for l in added[:-1]) and added[-1].strip() == "|> filter(fn: (r) => r._value > 0.0)",
      str(added))
check("as of fcc1 the canonical house power was the plain alias of the native load (what hd1 replaces)",
      "{{ states('sensor.ecco_clock_dongle_ecco_load_power') | float(0) | round(1) }}"
      in pre["home-assistant/packages/ecco_canonical_telemetry.yaml"])

print("")
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {PASSES} hd1 derived house load checks passed.")
print("These prove the package's templates against models of the dongle's publishing and of Home Assistant offline; they prove "
      "nothing about a live Home Assistant or the inverter.")
