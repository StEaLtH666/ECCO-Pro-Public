#!/usr/bin/env python3
"""Overview V2.1 (dashboard 7.21.1, post-export entry ovw2): offline proofs of the dashboard's changed logic and structure.

Reads the dashboard YAML (as of ovw2), runs the REAL button-card JavaScript templates and the apexcharts data generators under node with
a pinned clock and synthetic entity states, and compares them with the V2 dashboard (7.21.0, rebuilt by the exact ovw2 reverter). Display
only: nothing here connects to Home Assistant, ESPHome or InfluxDB, nothing is deployed, and no control is exercised. NODE (20 or newer)
IS REQUIRED: the checks that need it fail with a clear message when it is missing, they are never skipped.

  [1]  structure: the nine Overview sections and spans, the card order of the two columns that changed, Battery estimate replaced by
       Battery outlook, Today so far / Coming up / chart data-status strip present
  [2]  read-only: every card ovw2 adds has tap_action none and no service, script or write construct; the dashboard has exactly as many
       tap / service constructs as the 7.21.0 dashboard
  [3]  projection horizon (the 72 % at 00:30 defect): across a 24-hour grid the ECCO Today (Overview, Intelligence) and Smart Charge
       Strategy (four views) SOC at the target equals the 7.21.0 value everywhere EXCEPT between 00:00 and the target, where it no longer
       credits solar that cannot arrive before the target; labels name the day; an unreachable battery / sun entity shows an
       unavailable state, never NaN
  [4]  mutants: removing the horizon share, the SOC guard or the sun guard fails the projection checks above (a bare `states` put back
       in a chart generator is caught by the scan in [6])
  [5]  the new cards: Battery outlook, Today so far, Coming up, scheduled-session counters and the chart data-status strip, with
       synthetic entities (values, order, tomorrow tag, unavailable and missing data)
  [6]  charts: no apexcharts data_generator uses a bare `states`; the dead SOC Model series is gone and every dashArray entry has a series
  [7]  reserve wording: the modelled need is not called a minimum reserve; the static 15 % texts show the live ECCO setting
  [8]  entities: every entity id ovw2 introduces exists (a package template sensor name, a firmware sensor name, or a platform entity)
  [9]  version: dashboard 7.21.1 in the header and VERSION.yaml; tested_in_home_assistant stays false
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _ovw2_scope as O2  # noqa: E402  (the exact reverter of ovw2's dashboard edits: rebuilds the 7.21.0 dashboard, which carries FE1's time to reserve)
import _pex  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


DASH_REL = O2.DASHBOARD_REL
VERSION_REL = O2.VERSION_REL


PEX_REFUSALS: dict = {}


def as_of_ovw2(rel: str) -> str:
    """The file exactly as ovw2 leaves it (a later post-export entry's edits undone, so this suite keeps passing after one is appended)."""
    text = _pex.read(rel)   # PEX: the live file as the suites read it
    try:
        return _pex.as_of(rel, "ovw2", text)   # PEX: fails closed on any undeclared edit
    except AssertionError as ex:   # PEX refused (an undeclared edit): keep running on the live text, and fail the check recorded below
        PEX_REFUSALS[rel] = str(ex)[:160]
        return text


NEW_TEXT = as_of_ovw2(DASH_REL)
VER_TEXT = as_of_ovw2(VERSION_REL)
try:
    OLD_TEXT = O2.pre_ovw2_dashboard(NEW_TEXT)   # the 7.21.0 dashboard (f0ddeb4), byte for byte
except AssertionError as _ex:   # the text is no declared state (also reported by the [0] check): keep running so every later check still reports
    PEX_REFUSALS["reverter"] = str(_ex)[:160]
    OLD_TEXT = NEW_TEXT
SLUG = "ecco_clock_dongle"


class L(yaml.SafeLoader):
    pass


def load(text: str) -> dict:
    return yaml.load(text, Loader=L)


L.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
                        else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node))
NEW = load(NEW_TEXT)
OLD = load(OLD_TEXT)


def view(d: dict, path: str) -> dict:
    return next(v for v in d["views"] if v.get("path") == path)


def walk(o):
    yield o
    if isinstance(o, dict):
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def cards_named(d: dict, view_path: str, name: str) -> list:
    return [c for c in walk(view(d, view_path)) if isinstance(c, dict) and c.get("type") == "custom:button-card" and c.get("name") == name]


NEW_TEXT_OK = not PEX_REFUSALS
# ===========================================================================
print("[0] the files are declared states")
check("the dashboard and VERSION.yaml are exactly a state the post-export chain declares (PEX refuses an undeclared edit)", NEW_TEXT_OK, str(PEX_REFUSALS))

# ===========================================================================
print("[1] structure")
# ===========================================================================
ov = view(NEW, "ecco-overview")
secs = ov["sections"]
names = lambda s: [c.get("name") or (c.get("type") or "").replace("custom:", "") for c in s["cards"]]   # noqa: E731
check("the Overview keeps its nine sections and spans (4, 4, 3, 1, 2, 2, 3, 1, 4)", [s.get("column_span") for s in secs] == [4, 4, 3, 1, 2, 2, 3, 1, 4])
check("section 4 is still the Energy Actions card followed by the Known-Good Profile bar",
      names(secs[4]) == ["ecco-energy-actions-card", "Known-Good Profile"])
check("the decision-support column is ECCO Today, Today so far, Battery outlook, Scheduled sessions (Battery estimate is gone)",
      names(secs[5]) == ["ECCO Today", "Today so far", "Battery outlook", "Scheduled sessions"])
check("the slim right-hand column ends with the new Coming up card", names(secs[3])[-1] == "Coming up" and len(secs[3]["cards"]) == 5)
check("the Power Flow section is a data-status strip followed by the chart",
      len(secs[6]["cards"]) == 2 and secs[6]["cards"][0].get("variables", {}).get("msg") and secs[6]["cards"][1]["type"] == "custom:apexcharts-card")
flow_new = next(c for c in walk(ov) if isinstance(c, dict) and c.get("type") == "custom:ecco-energy-flow-card")
flow_old = next(c for c in walk(view(OLD, "ecco-overview")) if isinstance(c, dict) and c.get("type") == "custom:ecco-energy-flow-card")
check("the animated Energy Flow card configuration is byte-for-byte unchanged (every key, including grid_options)", flow_new == flow_old)
check("the hero, the Energy Actions card and the Known-Good Profile bar are unchanged",
      secs[0] == view(OLD, "ecco-overview")["sections"][0] and secs[4] == view(OLD, "ecco-overview")["sections"][4])
other_views_changed = sorted(v["path"] for v in NEW["views"] if v != view(OLD, v["path"]))
check("only the Overview, Intelligence, Tariffs, Control, Recommended, System views differ from 7.21.0 (the Weather & Solar, Inverter / Advanced, "
      "Fallback / Recovery, Safety and Manual Controls views are untouched)",
      other_views_changed == sorted(["ecco-overview", "ecco-intelligence", "ecco-tariffs", "ecco-control", "ecco-recommended", "ecco-system"]),
      str(other_views_changed))

# ===========================================================================
print("")
print("[2] read-only")
# ===========================================================================
NEW_CARD_NAMES = {"Today so far", "Coming up", "Battery outlook"}
new_cards = [c for n in NEW_CARD_NAMES for c in cards_named(NEW, "ecco-overview", n)]
new_cards += [c for c in walk(NEW) if isinstance(c, dict) and c.get("variables", {}).get("msg") and c.get("type") == "custom:button-card"]
check("the cards ovw2 adds exist (Battery outlook, Today so far, Coming up in its two places and three chart data-status strips)", len(new_cards) == 4 + 3, str(len(new_cards)))
bad_tap = [c.get("name") or "(strip)" for c in new_cards if (c.get("tap_action") or {}).get("action") != "none"]
check("each of them has tap_action none", not bad_tap, str(bad_tap))
WRITE_WORDS = re.compile(r"perform-action|call-service|callService|hass\.call|service:|turn_on|turn_off|set_value|press|more-info|navigate|url_path|fire-dom-event", re.I)
card_texts = [json.dumps(c) for c in new_cards]
check("no new card carries a service, script, press, toggle, navigation or write construct", not any(WRITE_WORDS.search(t) for t in card_texts))
ACTIONS = re.compile(r"(?m)^\s*(tap_action|hold_action|double_tap_action):[ \t]*\r?\n\s*action:\s*(\S+)")
def action_census(text):   # {(handler, action): count}
    census: dict = {}
    for m in ACTIONS.finditer(text):
        census[m.groups()] = census.get(m.groups(), 0) + 1
    return census
o_census, n_census = action_census(OLD_TEXT), action_census(NEW_TEXT)
added = {k: n_census.get(k, 0) - o_census.get(k, 0) for k in set(n_census) | set(o_census) if n_census.get(k, 0) != o_census.get(k, 0)}
check("compared with 7.21.0 the only tap / hold / double-tap handlers that were ADDED are `action: none` (no new service, navigation or toggle handler)",
      all(k[1] == "none" for k, v in added.items() if v > 0), str(added))
check("service and perform-action constructs are the same number as in 7.21.0",
      len(re.findall(r"perform-action|call-service", NEW_TEXT)) == len(re.findall(r"perform-action|call-service", OLD_TEXT)))

# ===========================================================================
print("")
print("[3] the SOC projection at the target time")
# ===========================================================================
NODE = shutil.which("node")
check("node is available (required, never skipped)", NODE is not None, "install Node 20 or newer")

RUNNER = r"""
const fs = require('fs');
const [spec, out] = process.argv.slice(2);
const S = JSON.parse(fs.readFileSync(spec, 'utf8'));
const RealDate = Date;
const results = [];
function fieldSource(card, field) {
  if (field.startsWith('variables.')) return (card.variables || {})[field.slice(10)];
  return (card.custom_fields || {})[field];
}
function findCard(dash, viewPath, name) {
  const v = dash.views.find(x => x.path === viewPath); let hit = null;
  (function walk(o) { if (hit) return; if (Array.isArray(o)) o.forEach(walk); else if (o && typeof o === 'object') {
    if (o.type === 'custom:button-card' && (o.name === name || (name === '#chart-status' && o.variables && o.variables.msg))) hit = o;
    Object.values(o).forEach(walk); } })(v);
  return hit;
}
function findSeries(dash, viewPath) {
  const v = dash.views.find(x => x.path === viewPath); const hit = [];
  (function walk(o) { if (Array.isArray(o)) o.forEach(walk); else if (o && typeof o === 'object') {
    if (o.type === 'custom:apexcharts-card' && Array.isArray(o.series)) o.series.forEach(s => { if (typeof s.data_generator === 'string') hit.push({ name: s.name, entity: s.entity, code: s.data_generator }); });
    Object.values(o).forEach(walk); } })(v);
  return hit;
}
for (const sc of S.scenarios) {
  const dash = S.dashboards[sc.dash];
  const states = {};
  for (const e of sc.states) states[e.entity_id] = e;
  const fixed = new RealDate(sc.clock).getTime();
  class FakeDate extends RealDate { constructor(...a) { if (a.length === 0) super(fixed); else super(...a); } static now() { return fixed; } }
  global.Date = FakeDate;
  let res;
  try {
    if (sc.kind === 'card') {
      const card = findCard(dash, sc.view, sc.card);
      if (!card) throw new Error('card not found: ' + sc.card);
      const src = fieldSource(card, sc.field);
      const m = String(src).match(/^\s*\[\[\[([\s\S]*)\]\]\]\s*$/);
      if (!m) throw new Error('not a [[[ ]]] template');
      const hass = { states, user: { name: 'test' } };
      const fn = new Function('states', 'hass', 'entity', 'config', 'variables', 'user', m[1]);
      res = { html: String(fn(states, hass, undefined, card, {}, hass.user)) };
    } else {
      const ser = findSeries(dash, sc.view).filter(s => s.name === sc.series);
      res = { n: ser.length, outs: ser.map(s => { try { const r = new Function('entity', 'start', 'end', 'hass', 'entities', s.code)(states[s.entity], new Date(), new Date(), { states }, []); return { points: r.length, first: r[0][1], last: r[r.length - 1][1] }; } catch (e) { return { error: String(e.message || e) }; } }) };
    }
  } catch (e) { res = { error: String(e.message || e) }; }
  global.Date = RealDate;
  results.push({ id: sc.id, ...res });
}
fs.writeFileSync(out, JSON.stringify(results));
"""


def run_node(dashboards: dict, scenarios: list) -> dict:
    """Runs every scenario in ONE node process; returns {id: result}."""
    if NODE is None:
        return {}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "runner.js").write_text(RUNNER, encoding="utf-8")
        (td / "spec.json").write_text(json.dumps({"dashboards": dashboards, "scenarios": scenarios}), encoding="utf-8")
        r = subprocess.run([NODE, str(td / "runner.js"), str(td / "spec.json"), str(td / "out.json")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900, env={**__import__("os").environ, "TZ": "Europe/London"})
        if r.returncode != 0:
            raise AssertionError("node failed: " + (r.stderr or r.stdout)[:400])
        return {x["id"]: x for x in json.loads((td / "out.json").read_text(encoding="utf-8"))}


BST = timezone(timedelta(hours=1))   # 12 October 2026 is in British Summer Time
DAY = datetime(2026, 10, 12, tzinfo=BST)
RISE, SET = 7 * 60 + 19, 18 * 60 + 19   # local minutes of sunrise and sunset on the test day


def iso(minute_of_day: int, day_offset: int = 0) -> str:
    return (DAY + timedelta(days=day_offset, minutes=minute_of_day)).isoformat()


def ent(eid: str, state, **attrs) -> dict:
    return {"entity_id": eid, "state": str(state), "attributes": attrs}


def sun_state(minute: int) -> dict:
    """sun.sun as Home Assistant reports it at local minute `minute` of the test day."""
    if minute < RISE:
        return ent("sun.sun", "below_horizon", next_rising=iso(RISE), next_setting=iso(SET))
    if minute < SET:
        return ent("sun.sun", "above_horizon", next_rising=iso(RISE, 1), next_setting=iso(SET))
    return ent("sun.sun", "below_horizon", next_rising=iso(RISE, 1), next_setting=iso(SET, 1))


FORECAST = 8.43


def remaining_solar(minute: int) -> float:
    """The blended forecast for the rest of the CURRENT calendar day: the whole day from local midnight until sunrise, then falling to 0 at sunset."""
    if minute < RISE:
        return FORECAST
    if minute < SET:
        return round(FORECAST * (SET - minute) / (SET - RISE), 3)
    return 0.0


def rates_event(day_offset: int = 0) -> dict:
    """Octopus-style half-hour rates for the test day: 8.2 p overnight (00:30-05:30), 29.8 p otherwise (so the cheap and peak bands exist)."""
    rows = []
    for k in range(48):
        m = k * 30
        p = 0.082 if 30 <= m < 330 else 0.298
        rows.append({"start": iso(m, day_offset), "end": iso(m + 30, day_offset), "value_inc_vat": p})
    name = "current_day_rates" if day_offset == 0 else "next_day_rates"
    return ent(f"event.octopus_energy_electricity_1234_5678_{name}", "2026-10-12T00:00:00", rates=rows)


def base_states(minute: int, soc: float = 47.0, load_w: float = 900.0, pv_w: float = 0.0, **over) -> list:
    d = {
        f"sensor.{SLUG}_ecco_battery_soc": ent(f"sensor.{SLUG}_ecco_battery_soc", soc),
        f"sensor.{SLUG}_ecco_pv_power": ent(f"sensor.{SLUG}_ecco_pv_power", pv_w),
        f"sensor.{SLUG}_ecco_load_power": ent(f"sensor.{SLUG}_ecco_load_power", load_w),
        f"sensor.{SLUG}_ecco_battery_output_power": ent(f"sensor.{SLUG}_ecco_battery_output_power", 900),
        f"sensor.{SLUG}_ecco_grid_power_ct_clamp": ent(f"sensor.{SLUG}_ecco_grid_power_ct_clamp", 20),
        f"sensor.{SLUG}_ecco_generator_port_power": ent(f"sensor.{SLUG}_ecco_generator_port_power", 0),
        f"sensor.{SLUG}_ecco_day_load_energy": ent(f"sensor.{SLUG}_ecco_day_load_energy", round(max(minute, 60) / 60 * 0.9, 2)),
        f"sensor.{SLUG}_ecco_day_pv_energy": ent(f"sensor.{SLUG}_ecco_day_pv_energy", 0 if minute < RISE else round(min(minute - RISE, SET - RISE) / 60 * 0.8, 2)),
        f"sensor.{SLUG}_ecco_battery_capacity_ah": ent(f"sensor.{SLUG}_ecco_battery_capacity_ah", 620),
        f"sensor.{SLUG}_ecco_day_grid_import": ent(f"sensor.{SLUG}_ecco_day_grid_import", 1.2),
        f"sensor.{SLUG}_ecco_day_grid_export": ent(f"sensor.{SLUG}_ecco_day_grid_export", 0.4),
        f"sensor.{SLUG}_ecco_day_battery_charge": ent(f"sensor.{SLUG}_ecco_day_battery_charge", 3.1),
        f"sensor.{SLUG}_ecco_day_battery_discharge": ent(f"sensor.{SLUG}_ecco_day_battery_discharge", 2.2),
        "sensor.ecco_solar_forecast_today": ent("sensor.ecco_solar_forecast_today", FORECAST),
        "sensor.ecco_solar_forecast_remaining": ent("sensor.ecco_solar_forecast_remaining", remaining_solar(minute)),
        "sensor.ecco_solar_forecast_power_now": ent("sensor.ecco_solar_forecast_power_now", 0),
        "sensor.ecco_config_charge_start_time": ent("sensor.ecco_config_charge_start_time", "00:30"),
        "sensor.ecco_config_minimum_reserve_soc": ent("sensor.ecco_config_minimum_reserve_soc", 15),
        "sensor.ecco_config_battery_capacity": ent("sensor.ecco_config_battery_capacity", 31.7),
        "sensor.ecco_battery_soc": ent("sensor.ecco_battery_soc", soc),
        "sensor.ecco_battery_energy_estimate": ent("sensor.ecco_battery_energy_estimate", round(31.7 * soc / 100, 3)),
        "sensor.ecco_predicted_soc_plus_1_hour_baseline": ent("sensor.ecco_predicted_soc_plus_1_hour_baseline", 43.3),
        "sensor.ecco_predicted_soc_0035": ent("sensor.ecco_predicted_soc_0035", 46.6),
        "sensor.ecco_expected_load_to_0035": ent("sensor.ecco_expected_load_to_0035", 0.13),
        "sensor.ecco_battery_outlook_last_scored_prediction": ent("sensor.ecco_battery_outlook_last_scored_prediction", 34.2),
        "sensor.ecco_battery_outlook_last_actual_soc": ent("sensor.ecco_battery_outlook_last_actual_soc", 36.0),
        "sensor.ecco_battery_outlook_last_error": ent("sensor.ecco_battery_outlook_last_error", 1.8),
        "sensor.ecco_battery_outlook_7_day_mae": ent("sensor.ecco_battery_outlook_7_day_mae", 1.5),
        "sensor.ecco_battery_outlook_7_day_bias": ent("sensor.ecco_battery_outlook_7_day_bias", 0.6),
        "sun.sun": sun_state(minute),
        "event.octopus_energy_electricity_1234_5678_current_day_rates": rates_event(0),
        "event.octopus_energy_electricity_1234_5678_next_day_rates": rates_event(1),
        "sensor.octopus_energy_electricity_1234_5678_current_rate": ent("sensor.octopus_energy_electricity_1234_5678_current_rate", 0.298,
                                                                          current_day_min_rate=0.082, current_day_max_rate=0.298),
    }
    for i, (t, ch, soc_t) in enumerate([("00:30", "Grid", 100), ("05:30", "None", 0), ("12:00", "None", 0), ("16:35", "None", 0),
                                         ("22:00", "None", 0), ("00:25", "None", 0)], start=1):
        d[f"sensor.{SLUG}_ecco_timezone{i}_time"] = ent(f"sensor.{SLUG}_ecco_timezone{i}_time", t)
        d[f"sensor.{SLUG}_ecco_timezone{i}_charge"] = ent(f"sensor.{SLUG}_ecco_timezone{i}_charge", ch)
        d[f"sensor.{SLUG}_ecco_timezone{i}_soc"] = ent(f"sensor.{SLUG}_ecco_timezone{i}_soc", soc_t)
        d[f"sensor.{SLUG}_ecco_timezone{i}_power"] = ent(f"sensor.{SLUG}_ecco_timezone{i}_power", 8000)
    d[f"sensor.{SLUG}_ecco_timezone1_soc"] = ent(f"sensor.{SLUG}_ecco_timezone1_soc", 100)
    for key in ("free_power", "dump_to_grid"):
        d[f"input_boolean.ecco_{key}_schedule_armed"] = ent(f"input_boolean.ecco_{key}_schedule_armed", "off")
        d[f"input_datetime.ecco_{key}_schedule_start"] = ent(f"input_datetime.ecco_{key}_schedule_start", "2026-10-12 11:00:00")
        d[f"input_number.ecco_{key}_schedule_power"] = ent(f"input_number.ecco_{key}_schedule_power", 8000)
        d[f"input_number.ecco_{key}_schedule_duration"] = ent(f"input_number.ecco_{key}_schedule_duration", 60)
        d[f"sensor.ecco_{key}_schedule_status"] = ent(f"sensor.ecco_{key}_schedule_status", "IDLE", last_result="STARTED OK")
        for kind, v in (("start_successes", 2), ("restore_successes", 2), ("failures", 0)):
            d[f"sensor.{SLUG}_{key}_{kind}_since_boot"] = ent(f"sensor.{SLUG}_{key}_{kind}_since_boot", v)
    d["input_number.ecco_dump_to_grid_schedule_stop_soc"] = ent("input_number.ecco_dump_to_grid_schedule_stop_soc", 50)
    for k, v in over.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return list(d.values())


CARDS = [("ovw", "ecco-overview", "ECCO Today", "recommendation"), ("int", "ecco-intelligence", "ECCO Today", "recommendation"),
         ("scs-int", "ecco-intelligence", "Smart Charge Strategy", "body"), ("scs-tar", "ecco-tariffs", "Smart Charge Strategy", "body"),
         ("scs-con", "ecco-control", "Smart Charge Strategy", "body"), ("scs-rec", "ecco-recommended", "Smart Charge Strategy", "body")]
MINUTES = list(range(0, 24 * 60, 30)) + [14, 25, 29, 31, 44, 445, 1000]   # every half hour plus the minutes around the 00:30 target
SOCS = (20.0, 47.0, 85.0)


def grid_scenarios() -> list:
    out = []
    for dash in ("old", "new"):
        for minute in MINUTES:
            for soc in SOCS:
                clock = (DAY + timedelta(minutes=minute)).astimezone(timezone.utc).isoformat()
                st = base_states(minute, soc=soc)
                for tag, v, name, field in CARDS:
                    out.append({"id": f"{dash}|{tag}|{minute}|{soc}", "kind": "card", "dash": dash, "view": v, "card": name, "field": field,
                                "clock": clock, "states": st})
    return out


def pct_pair(text: str):
    """(likely, conservative) SOC percentages of an ECCO Today text, or the single 'Expected at' percentage of a Smart Charge text."""
    plain = re.sub(r"<[^>]+>", " ", text)
    m = re.search(r"Likely SOC at .*? is (?:only )?(\d+)%.*?(\d+)%", plain)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"Expected at [\d:]+ (?:today |tomorrow )?(-?\d+|NaN)%", plain)
    return (int(m.group(1)),) if m and m.group(1) != "NaN" else None


def evaluate(new_text: str) -> dict:
    """All scenario results for the V2.1 dashboard `new_text` and the 7.21.0 dashboard; one node run."""
    dashboards = {"old": load(OLD_TEXT), "new": load(new_text)}
    scen = grid_scenarios()
    sun_missing = base_states(14, soc=47.0, **{"sun.sun": None})
    soc_missing = base_states(14, soc=47.0, **{f"sensor.{SLUG}_ecco_battery_soc": ent(f"sensor.{SLUG}_ecco_battery_soc", "unavailable")})
    clock14 = (DAY + timedelta(minutes=14)).astimezone(timezone.utc).isoformat()
    for tag, v, name, field in CARDS:
        scen.append({"id": f"new|sunmissing|{tag}", "kind": "card", "dash": "new", "view": v, "card": name, "field": field, "clock": clock14, "states": sun_missing})
        scen.append({"id": f"new|socmissing|{tag}", "kind": "card", "dash": "new", "view": v, "card": name, "field": field, "clock": clock14, "states": soc_missing})
    for v in ("ecco-overview", "ecco-intelligence", "ecco-system"):
        scen.append({"id": f"new|gen|{v}", "kind": "series", "dash": "new", "view": v, "series": "SOC Model", "clock": clock14, "states": base_states(14)})
        scen.append({"id": f"old|gen|{v}", "kind": "series", "dash": "old", "view": v, "series": "SOC Model", "clock": clock14, "states": base_states(14)})
    return run_node(dashboards, scen)


def judge(res: dict) -> list:
    """Every failed expectation of the projection checks, by name."""
    bad = []
    if not res:
        return ["no node results"]
    err = [k for k, v in res.items() if "error" in v and "|gen|" not in k and "missing" not in k]
    if err:
        bad.append(f"scenarios raised: {err[:3]}")
    window_old_wrong = 0
    for minute in MINUTES:
        for soc in SOCS:
            for tag, *_ in CARDS:
                o, n = res.get(f"old|{tag}|{minute}|{soc}", {}), res.get(f"new|{tag}|{minute}|{soc}", {})
                po, pn = pct_pair(o.get("html", "")), pct_pair(n.get("html", ""))
                if po is None or pn is None:
                    bad.append(f"unparsed {tag} {minute} {soc}")
                    continue
                if 0 <= minute < 30:   # between local midnight and the 00:30 target: the defect window
                    if not all(x <= soc + 0.5 for x in pn):
                        bad.append(f"{tag} at minute {minute}: new SOC {pn} credits solar that cannot arrive before the target (soc {soc})")
                    if not any(a > b for a, b in zip(po, pn)):
                        pass
                    else:
                        window_old_wrong += 1
                elif po != pn:
                    bad.append(f"{tag} at minute {minute} soc {soc}: 7.21.0 {po} != 7.21.1 {pn} outside the defect window")
                text = n.get("html", "")
                label = "today" if 0 <= minute < 30 else "tomorrow"
                if f"00:30 {label}" not in re.sub(r"<[^>]+>", " ", text):
                    bad.append(f"{tag} at minute {minute}: the label does not say '00:30 {label}'")
    if window_old_wrong < 20:
        bad.append(f"the 7.21.0 dashboard did not show the overstated SOC in the defect window ({window_old_wrong})")
    for tag, *_ in CARDS:
        s, c = res.get(f"new|sunmissing|{tag}", {}).get("html", ""), res.get(f"new|socmissing|{tag}", {}).get("html", "")
        if tag in ("ovw", "int") and "Projection unavailable" not in s:
            bad.append(f"{tag}: a missing sun entity does not give 'Projection unavailable'")
        if "Battery data unavailable" not in c or "NaN" in c:
            bad.append(f"{tag}: an unavailable battery SOC does not give 'Battery data unavailable' without NaN")
    for v in ("ecco-overview", "ecco-intelligence", "ecco-system"):
        g = res.get(f"new|gen|{v}", {})
        if g.get("n") != 0:
            bad.append(f"the {v} chart still has a SOC Model series ({g})")
    return bad


RES = evaluate(NEW_TEXT) if NODE else {}
JUDGED = judge(RES)
n_grid = len(MINUTES) * len(SOCS) * len(CARDS)
check(f"{n_grid} grid scenarios ran (6 cards x {len(MINUTES)} times x {len(SOCS)} SOC values) and none raised", bool(RES) and not any("raised" in b for b in JUDGED), str(JUDGED[:3]))
check("outside 00:00 to the 00:30 target the 7.21.1 SOC equals the 7.21.0 value for every card (behaviour preserved)", not any("outside the defect window" in b for b in JUDGED), str([b for b in JUDGED if "outside" in b][:3]))
check("between 00:00 and 00:30 the SOC at the target never exceeds the current SOC (no solar credit that cannot arrive in time)",
      not any("credits solar" in b for b in JUDGED), str([b for b in JUDGED if "credits" in b][:3]))
check("the 7.21.0 dashboard did show the overstated SOC in that window (the test proves a real defect, not a vacuous one)", not any("did not show" in b for b in JUDGED), str(JUDGED[:2]))
check("every label names the target day: '00:30 today' before the target, '00:30 tomorrow' after it", not any("label" in b for b in JUDGED), str([b for b in JUDGED if "label" in b][:3]))
check("a missing sun entity gives 'Projection unavailable' (ECCO Today) and an unavailable battery SOC gives 'Battery data unavailable' with no NaN (all six cards)",
      not any(("unavailable" in b) for b in JUDGED), str([b for b in JUDGED if "unavailable" in b][:3]))
no_nan = all("NaN" not in RES.get(f"new|{tag}|{m}|{s}", {}).get("html", "") for m in MINUTES for s in SOCS for tag, *_ in CARDS) if RES else False
check("no card renders NaN in any grid scenario", no_nan)
o_reported = pct_pair(RES.get("old|ovw|14|47.0", {}).get("html", "")) if RES else None
n_reported = pct_pair(RES.get("new|ovw|14|47.0", {}).get("html", "")) if RES else None
check("the reported case (00:14, SOC 47 %; the screenshot read 72 % likely / 68 % conservative): 7.21.0 projects 20 points or more above the "
      "current SOC, 7.21.1 projects no higher than the current SOC and no more than 3 points below it",
      bool(o_reported and n_reported) and all(x >= 47 + 20 for x in o_reported) and all(44 <= x <= 47 for x in n_reported), f"{o_reported} -> {n_reported}")

# ===========================================================================
print("")
print("[4] mutants: each broken copy must fail the checks above")
# ===========================================================================
MUTANTS = [
    ("the horizon share is not applied (the 7.21.0 behaviour)", NEW_TEXT.replace("correctedSolar*solarShare-loadToCheap", "correctedSolar-loadToCheap")),
    ("the battery-SOC guard is removed", NEW_TEXT.replace("!Number.isFinite(Number(socRaw))", "false").replace("|| !Number.isFinite(Number(socRaw))", "")),
    ("the sun guard is removed (unknown sun credits solar)", NEW_TEXT.replace("if (!set || Number.isNaN(set.getTime())) return { known: false, share: null, partial: false };",
                                                                           "if (!set || Number.isNaN(set.getTime())) return { known: true, share: 1, partial: false };")),
]
for what, text in MUTANTS:
    if text == NEW_TEXT:
        check(f"mutant applies: {what}", False, "the mutation did not change the text")
        continue
    mres = evaluate(text) if NODE else {}
    check(f"mutant fails the projection checks: {what}", bool(judge(mres)))
# the chart check is a text scan; its mutant (a bare `states` put back) is exercised in [6]

# ===========================================================================
print("")
print("[5] the new cards, with synthetic entities")
# ===========================================================================


def card_text(dash_key: str, view_path: str, name: str, field: str, minute: int, states: list, dash=None) -> str:
    sc = [{"id": "x", "kind": "card", "dash": "d", "view": view_path, "card": name, "field": field,
           "clock": (DAY + timedelta(minutes=minute)).astimezone(timezone.utc).isoformat(), "states": states}]
    r = run_node({"d": dash or NEW}, sc)["x"]
    raw = r.get("html", "ERR " + r.get("error", "")).replace("&nbsp;", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()


bo = card_text("n", "ecco-overview", "Battery outlook", "body", 14, base_states(14))
check("Battery outlook: stored energy, the ECCO reserve SETTING, next hour, the learned load-only floor at 00:35 and its accuracy",
      all(s in bo for s in ("Stored 14.9 kWh", "Reserve setting 15 %", "Next hour 43.3 %", "46.6 % at 00:35", "expected load 0.13 kWh",
                            "last night 34.2 % → 36.0 % (+1.8 pts)", "7-day average miss 1.5 pts", "bias +0.6")), bo[:300])
check("Battery outlook says the reserve setting is separate from the Dump to Grid stop and the outlook ignores solar",
      "separate from the Dump to Grid stop" in bo and "load only, ignores solar" in bo)
bo2 = card_text("n", "ecco-overview", "Battery outlook", "body", 14, base_states(14, **{"sensor.ecco_predicted_soc_0035": None}))
check("Battery outlook: without the learned sensors it says the outlook is not available yet and never shows a number for it",
      "not available yet" in bo2 and "46.6" not in bo2 and "Stored 14.9 kWh" in bo2, bo2[:200])
bo3 = card_text("n", "ecco-overview", "Battery outlook", "body", 14, base_states(14, **{"sensor.ecco_config_minimum_reserve_soc": ent("sensor.ecco_config_minimum_reserve_soc", "unavailable")}))
check("Battery outlook: an unavailable reserve setting shows '--', not 0 or NaN", "Reserve setting -- %" in bo3 and "NaN" not in bo3, bo3[:200])

ts = card_text("n", "ecco-overview", "Today so far", "body", 14, base_states(14))
check("Today so far: the six daily totals of the dongle in kWh", all(s in ts for s in ("PV", "House", "Imported 1.2 kWh", "Exported 0.4 kWh", "Battery in 3.1 kWh", "Battery out 2.2 kWh")), ts)
ts2 = card_text("n", "ecco-overview", "Today so far", "body", 14, base_states(14, **{f"sensor.{SLUG}_ecco_day_grid_import": ent(f"sensor.{SLUG}_ecco_day_grid_import", "unavailable")}))
check("Today so far: an unavailable total shows '--' (never 0 or NaN)", "Imported -- kWh" in ts2 and "NaN" not in ts2, ts2)

cu = card_text("n", "ecco-overview", "Coming up", "body", 14, base_states(14))
order = [cu.find(s) for s in ("00:30 Grid charge starts · 100 % target", "00:30 Cheap rate · 8.2 p/kWh", "05:30 Grid charge ends", "05:30 Peak rate · 29.8 p/kWh", "07:19 Sunrise", "18:19 Sunset")]
check("Coming up at 00:14: grid-charge window, tariff changes, sunrise and sunset, each once, in time order",
      all(p >= 0 for p in order) and order == sorted(order), cu)
check("Coming up: 'in 16 min' for the 00:30 events, and nothing past the next 24 hours", "in 16 min" in cu and "tomorrow" not in cu.split("18:19")[0], cu)
cu_noon = card_text("n", "ecco-overview", "Coming up", "body", 12 * 60, base_states(12 * 60))
check("Coming up at midday: events after midnight carry the 'tomorrow' tag and the list is capped at eight rows",
      "tomorrow" in cu_noon and len(re.findall(r"\bin \d+ (?:min|h)", cu_noon)) <= 8, cu_noon)
armed = base_states(14, **{"input_boolean.ecco_free_power_schedule_armed": ent("input_boolean.ecco_free_power_schedule_armed", "on"),
                           "input_datetime.ecco_free_power_schedule_start": ent("input_datetime.ecco_free_power_schedule_start", "2026-10-12 02:00:00")})
check("Coming up lists an armed session (and only an armed one)", "Free Power session · armed" in card_text("n", "ecco-overview", "Coming up", "body", 14, armed) and "session" not in cu)
bare = card_text("n", "ecco-overview", "Coming up", "body", 14, [e for e in base_states(14) if e["entity_id"] != "sun.sun" and not e["entity_id"].startswith(("event.", f"sensor.{SLUG}_ecco_timezone"))])
check("Coming up with no sun, tariff or TOU data says so and shows no event", "No sun, tariff or session events found" in bare, bare)

ss = card_text("n", "ecco-overview", "Scheduled sessions", "body", 14, base_states(14))
check("Scheduled sessions: per-mode counters since the dongle last restarted (started, restored, failed)",
      ss.count("Since the dongle last restarted: 2 started · 2 restored · 0 failed") == 2, ss)

strip_new_day = card_text("n", "ecco-overview", "#chart-status", "variables.msg", 25, base_states(25))
strip_day = card_text("n", "ecco-overview", "#chart-status", "variables.msg", 12 * 60, base_states(12 * 60))
strip_bad = card_text("n", "ecco-overview", "#chart-status", "variables.msg", 12 * 60, base_states(12 * 60, **{
    f"sensor.{SLUG}_ecco_grid_power_ct_clamp": ent(f"sensor.{SLUG}_ecco_grid_power_ct_clamp", "unavailable"),
    f"sensor.{SLUG}_ecco_pv_power": ent(f"sensor.{SLUG}_ecco_pv_power", "unknown")}))
check("chart status: the first 90 minutes of a day say it is a new day (25 min so far)", "New day." in strip_new_day and "25 min so far" in strip_new_day, strip_new_day)
check("chart status: later in the day with everything reporting it says nothing (the strip is hidden)", strip_day == "", strip_day)
check("chart status: an unreachable sensor is named and called missing data, not a quiet day (it wins over the new-day note)",
      "Not reporting now: Solar, Grid" in strip_bad and "missing data, not a quiet day" in strip_bad, strip_bad)
strip_both = card_text("n", "ecco-overview", "#chart-status", "variables.msg", 25, base_states(25, **{f"sensor.{SLUG}_ecco_battery_soc": ent(f"sensor.{SLUG}_ecco_battery_soc", "unavailable")}))
check("chart status: missing data at 00:25 is still reported as missing, not hidden behind the new-day note", "Not reporting now: SOC" in strip_both and "New day" not in strip_both, strip_both)
hidden_cards = [c for c in walk(NEW) if isinstance(c, dict) and c.get("variables", {}).get("msg")]
check("the strip hides itself with display none when it has nothing to say (all three charts)",
      len(hidden_cards) == 3 and NEW_TEXT.count("- display: '[[[ return variables.msg ? \"block\" : \"none\"; ]]]'") == 3)

# ---- the load the projection assumes is stated (display transparency; the model is unchanged) ----
# 14:00 (840 min): the daily load total is 12.6 kWh (0.9 kW average over 14 h) and the load right now is 4 kW: blend 0.65 x 0.9 + 0.35 x 4.0 = 1.985 -> "2.0 kW"
spike = base_states(840, soc=75.0, load_w=4000.0)
for view_path in ("ecco-overview", "ecco-intelligence"):
    today = card_text("n", view_path, "ECCO Today", "recommendation", 840, spike)
    check(f"ECCO Today ({view_path}) states the assumed average house load, 2.0 kW for a 4 kW load right now on a 0.9 kW day",
          "Assumes about 2.0 kW average house load until then (65% today's average, 35% the load right now)" in today, today[:400])
    old_today = card_text("n", view_path, "ECCO Today", "recommendation", 840, spike, dash=OLD)
    check(f"... and the 7.21.0 text had no such statement ({view_path})", "Assumes about" not in old_today)
    check(f"... and says nothing about a load when no projection can be made, i.e. sun times missing ({view_path})",
          "Assumes about" not in card_text("n", view_path, "ECCO Today", "recommendation", 14, base_states(14, **{"sun.sun": None})))
check("the assumed load is a statement only: the SOC figures of the grid scenarios did not change with it (the equality checks in [3] still hold)",
      not any("outside the defect window" in b for b in JUDGED))
LAST = "overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow-wrap:anywhere;\">Last result:"
check("Scheduled sessions: the 'Last result' line wraps (up to three lines) (it was cut off with an ellipsis, hiding the reason a session failed)",
      NEW_TEXT.count(LAST) == 1 and OLD_TEXT.count("text-overflow:ellipsis;white-space:nowrap;\">Last result:") == 1
      and "text-overflow:ellipsis;white-space:nowrap;\">Last result:" not in NEW_TEXT)
# ---- text that used to be cut off (found by a 1:1 render): button-card fields inherit white-space: nowrap ----
def field_styles(card, field):
    return [tuple(d.items())[0] for d in ((card.get("styles") or {}).get("custom_fields") or {}).get(field) or []]


NOWRAP_OUT = ("white-space", "normal")
missing_wrap = [n for n in ("Today so far", "Battery outlook", "Scheduled sessions", "Coming up")
                if any(NOWRAP_OUT not in field_styles(c, "body") for c in cards_named(NEW, "ecco-overview", n))]
check("every card V2.1 adds to the Overview opts out of the nowrap its field inherits (white-space: normal), so no text is cut off by the card edge "
      "(the Battery outlook accuracy line had lost its 7-day figures)", not missing_wrap, str(missing_wrap))
strips_all = [c for c in walk(NEW) if isinstance(c, dict) and c.get("variables", {}).get("msg")]
check("...and so do the three chart status strips (a long note must wrap on a phone)",
      len(strips_all) == 3 and all(NOWRAP_OUT in field_styles(c, "note") for c in strips_all))
check("Coming up: the label column can shrink and wrap (minmax(0,1fr)) instead of pushing the time out of the card, and labels are left-aligned",
      NEW_TEXT.count("grid-template-columns:8px minmax(0,1fr) auto;gap:8px") == 2 and "grid-template-columns:8px 1fr auto;gap:8px;align-items:baseline" not in NEW_TEXT
      and 'color:rgba(255,255,255,.80);text-align:left;"><b style="font-size:13px;color:#fff;">${hhmm(e.t)}' in NEW_TEXT)
OV_TEXT = NEW_TEXT[NEW_TEXT.index("  - title: Overview\n"):NEW_TEXT.index("  - title: Weather & Solar\n")]
check("the Overview's Grid Status headline and subline and the Tariff now summary wrap instead of losing their unit / tail on a narrow card, "
      "and the Current Plan countdown wraps and its mode pill is smaller so the title is not cut to 'Current ...'",
      'line-height:1.2;white-space:normal;color:${colour};">${flow}</div>' in OV_TEXT
      and 'margin-top:2px;white-space:normal;">${detail}</div>' in OV_TEXT
      and 'margin-top:6px;white-space:normal;">Today ${p(cheap)}' in OV_TEXT
      and "                next:\n                  - justify-self: stretch\n                  - white-space: normal\n" in OV_TEXT
      and "display:inline-block;padding:4px 8px;border-radius:999px;" in OV_TEXT)
# ---- responsive placement of Coming up (final responsive polish) ----
VIS_WIDE, VIS_NARROW = "(min-width: 1696px)", "(max-width: 1695px)"
cu_cards = cards_named(NEW, "ecco-overview", "Coming up")
vis = lambda c: [(v.get("condition"), v.get("media_query")) for v in (c.get("visibility") or [])]   # noqa: E731
check("Coming up exists in two places: the right-hand status column (four columns) and under Electrical detail (narrower pages)",
      len(cu_cards) == 2 and names(secs[3])[-1] == "Coming up" and names(secs[7]) == ["Electrical detail", "Coming up"], str([names(s) for s in secs]))
check("each copy has exactly one Home Assistant screen visibility condition: min-width 1696 px in the right-hand column, the complementary max-width 1695 px "
      "under Electrical detail",
      vis(secs[3]["cards"][-1]) == [("screen", VIS_WIDE)] and vis(secs[7]["cards"][-1]) == [("screen", VIS_NARROW)], str(vis(secs[3]["cards"][-1])) + str(vis(secs[7]["cards"][-1])))
check("the two queries are exact complements at 1696 px = 1440 px of content (where the sections view switches to four columns, measured in the browser) "
      "+ the 256 px docked sidebar, so exactly one copy shows",
      int(re.search(r"min-width: (\d+)px", VIS_WIDE).group(1)) - 1 == int(re.search(r"max-width: (\d+)px", VIS_NARROW).group(1)) == 1440 + 256 - 1)
no_vis = lambda c: {k: v for k, v in c.items() if k != "visibility"}   # noqa: E731
check("the two copies are identical apart from their visibility condition (one set of card logic, tested once above)", no_vis(secs[3]["cards"][-1]) == no_vis(secs[7]["cards"][-1]))
check("no other Overview card carries a visibility condition (other views already use it for the recovery cards and are byte-identical to ovw1's): "
      "the change is confined to the two Coming up cards",
      sum(1 for n in walk(view(NEW, "ecco-overview")) if isinstance(n, dict) and "visibility" in n and n.get("type")) == 2
      and not any("visibility" in n for n in walk(view(OLD, "ecco-overview")) if isinstance(n, dict)))
check("the Overview's Electrical detail rows can shrink and wrap their label (the values overhung a phone card by 5 px)",
      "grid-template-columns:8px minmax(0,1fr) auto;align-items:center;gap:7px;padding:4px 0;" in OV_TEXT
      and 'color:rgba(255,255,255,.62);white-space:normal;">${r[0]}' in OV_TEXT)
sec5 = {c.get("name"): (c.get("grid_options") or {}).get("columns") for c in secs[5]["cards"]}
check("section 5 widths: ECCO Today and Scheduled sessions are full width, Today so far and Battery outlook share a row at 12 of the section's 24 "
      "columns each (Scheduled sessions had sat in half of the column with the other half empty)",
      sec5 == {"ECCO Today": "full", "Today so far": 12, "Battery outlook": 12, "Scheduled sessions": "full"}, str(sec5))
check("the two session rows of Scheduled sessions sit side by side when there is room (auto-fit, 300 px minimum, never wider than the card) and stack when there is not",
      NEW_TEXT.count("grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:4px 16px;") == 1)
sf = NEW_TEXT[NEW_TEXT.index("            name: Today so far\n"):NEW_TEXT.index("          # ---- BATTERY OUTLOOK")]
check("Today so far: the tiles fill the card (stretched field, equal rows, centred tile content) instead of floating in a band of empty space",
      "                  - align-self: stretch\n" in sf and "grid-auto-rows:1fr;gap:8px;height:100%;" in sf and "display:flex;flex-direction:column;justify-content:center;" in sf)

# ===========================================================================
print("")
print("[6] charts")
# ===========================================================================
BARE_STATES = re.compile(r"(?<![.\w])states\[")
gens = [(v["path"], s) for v in NEW["views"] for c in walk(v) if isinstance(c, dict) and c.get("type") == "custom:apexcharts-card"
        for s in (c.get("series") or []) if isinstance(s, dict) and s.get("data_generator")]
check("no apexcharts data_generator reads a bare `states` (only the card's own hass is in scope there)",
      not any(BARE_STATES.search(s["data_generator"]) for _p, s in gens), str([p for p, s in gens if BARE_STATES.search(s["data_generator"])]))
check("7.21.0 had that defect in three generators (the proof is not vacuous)", sum(1 for v in OLD["views"] for c in walk(v) if isinstance(c, dict) and c.get("type") == "custom:apexcharts-card"
                                                                           for s in (c.get("series") or []) if isinstance(s, dict) and s.get("data_generator") and BARE_STATES.search(s["data_generator"])) == 3)
check("the dead SOC Model series is gone from every chart", not any(isinstance(s, dict) and s.get("name") == "SOC Model" for v in NEW["views"] for c in walk(v)
                                                                      if isinstance(c, dict) and c.get("type") == "custom:apexcharts-card" for s in (c.get("series") or [])))
power = [c for v in NEW["views"] for c in walk(v) if isinstance(c, dict) and c.get("type") == "custom:apexcharts-card"
         and "Power Flow Today" in str((c.get("header") or {}).get("title", ""))]
check("the three Power Flow charts have five series and a dashArray of five entries", len(power) == 3 and all(len(c["series"]) == 5 and len(c["apex_config"]["stroke"]["dashArray"]) == 5 for c in power))
check("mutant: a bare `states` put back in a generator is caught by the scan", bool(BARE_STATES.search("const forecast=num(states['sensor.x']);")))

# ===========================================================================
print("")
print("[7] reserve wording")
# ===========================================================================
check("no card calls the modelled need a minimum reserve (Smart Charge Strategy says 'Modelled reserve need')",
      "Minimum reserve needed" not in NEW_TEXT and NEW_TEXT.count("Modelled reserve need") == 4 and NEW_TEXT.count("The modelled reserve need is an energy-security estimate") == 4)
check("the static 'Suggested 15%' and '15% starting point' texts are gone; both rows read the live ECCO setting",
      "Suggested 15%" not in NEW_TEXT and "15% starting point" not in NEW_TEXT and NEW_TEXT.count("${rs.toFixed(0)}% (current setting)") == 2)
sa = [c for n in ("Battery Policy",) for c in cards_named(NEW, "ecco-control", n)]
txt = card_text("n", "ecco-control", "Battery Policy", "body", 14, base_states(14))
check("the Control view's Battery Policy shows the live setting (15 % -> '15% (current setting)', unavailable -> 'Setting unavailable')",
      "15% (current setting)" in txt and "Setting unavailable" in card_text("n", "ecco-control", "Battery Policy", "body", 14, base_states(14, **{"sensor.ecco_config_minimum_reserve_soc": None})))
check("the Overview reserve tile reads sensor.ecco_config_minimum_reserve_soc (the ECCO setting), not the Dump to Grid stop", "sensor.ecco_config_minimum_reserve_soc" in json.dumps(cards_named(NEW, "ecco-overview", "Battery outlook")[0]))

# ===========================================================================
print("")
print("[8] entities ovw2 introduces")
# ===========================================================================
ENT = re.compile(r"\b(?:sensor|binary_sensor|input_boolean|input_number|input_datetime|number|select|switch|event|sun)\.[a-z0-9_]+")
new_ids = {e for e in set(ENT.findall(NEW_TEXT)) - set(ENT.findall(OLD_TEXT)) if not e.endswith("_")}   # a trailing `_` is a template prefix (id built in JS)
pkgs = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "home-assistant" / "packages").glob("*.yaml")))
fw_names = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "firmware").glob("*.yaml")))


def slug(s: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")


pkg_names = {slug(m) for m in re.findall(r"(?m)^\s*-\s*name:\s*(.+?)\s*$", pkgs)}
fw_name_slugs = {slug(m) for m in re.findall(r"(?m)^\s*(?:name|friendly_name):\s*\"?(.+?)\"?\s*$", fw_names)}
unknown = []
for e in sorted(new_ids):
    dom, obj = e.split(".", 1)
    if dom == "sun" and obj == "sun":
        continue
    if obj.startswith(SLUG + "_"):   # a dongle entity: Home Assistant names it <slug>_<firmware name>
        if slug(obj[len(SLUG) + 1:]) in fw_name_slugs or any(slug(obj[len(SLUG) + 1:]) == n for n in fw_name_slugs):
            continue
        # derived names (ecco_timezone1_time ...) are matched against the firmware's name templates below
        if re.match(r"ecco_timezone[1-6]_(time|power|soc|charge)$", obj[len(SLUG) + 1:]) or re.match(r"(free_power|dump_to_grid)_(start_successes|restore_successes|failures)_since_boot$", obj[len(SLUG) + 1:]):
            continue
        unknown.append(e)
    elif dom in ("sensor", "binary_sensor") and (obj in pkg_names or obj in {slug(n) for n in pkg_names}):
        continue
    elif dom == "event" and "octopus_energy_electricity" in obj:
        continue
    else:
        unknown.append(e)
check("every entity id ovw2 introduces is a package template sensor, a known dongle entity family or a platform entity", not unknown, str(unknown[:6]))
check("the 7-day outlook score ids are the ones the package names produce (…_7_day_mae / …_7_day_bias), and the wrong …_7d_… ids are gone",
      "ECCO Battery Outlook 7 Day MAE" in pkgs and "ECCO Battery Outlook 7 Day Bias" in pkgs
      and "sensor.ecco_battery_outlook_7d_mae" not in NEW_TEXT and "sensor.ecco_battery_outlook_7d_bias" not in NEW_TEXT
      and NEW_TEXT.count("sensor.ecco_battery_outlook_7_day_mae") == 2 and NEW_TEXT.count("sensor.ecco_battery_outlook_7_day_bias") == 2)

# ===========================================================================
print("")
print("[9] version")
# ===========================================================================
ver_text = VER_TEXT
ver = yaml.safe_load(ver_text)
check("VERSION.yaml: dashboard 7.21.1 (staged: tested_in_home_assistant false)",
      ver["current"]["dashboard"]["version"] == "7.21.1" and ver["current"]["dashboard"]["tested_in_home_assistant"] is False)
check("the dashboard header carries the v7.21.1 note and keeps the v7.20.0 one", "# v7.21.1 (OVW2, STAGED / NOT LIVE-PROVEN)" in NEW_TEXT and "# v7.20.0 (OVW1, STAGED / NOT LIVE-PROVEN)" in NEW_TEXT)
check("the file still starts with the pinned first line", NEW_TEXT.startswith("# ECCO Pro Dashboard v7.16.0"))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All Overview V2.1 dashboard checks PASSED.")
print("NOTE: this proves the dashboard's own JavaScript and structure offline; it does not prove how Home Assistant renders it. The")
print("dashboard remains STAGED / NOT LIVE-PROVEN.")
