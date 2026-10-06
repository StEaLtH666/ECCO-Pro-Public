#!/usr/bin/env python3
"""Offline tests for the Scheduled Dump to Grid package and its Free Power
schedule-overlap counterpart (2026-09-26 pre-live hardening).

Structural checks (helper/entity mapping to the card + dashboard, deployment
manifest, no direct register-write services) plus BEHAVIOURAL evaluation of
the packages' own Jinja templates (schedule overlap, TOU charging-slot
overlap) using jinja2 with small stand-ins for the Home Assistant template
functions they use (states, as_timestamp, timestamp_local, the `match` test).

NOTE: this does not prove the templates render identically inside a real
Home Assistant instance - only `ha core check` plus live observation can
prove that. The package remains STAGED / NOT LIVE-PROVEN.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[2]
DUMP_PKG = ROOT / "home-assistant" / "packages" / "ecco_dump_to_grid_schedule.yaml"
FP_PKG = ROOT / "home-assistant" / "packages" / "ecco_free_power_schedule.yaml"
DASHBOARD = ROOT / "home-assistant" / "dashboards" / "ecco_pro.yaml"
MANIFEST = ROOT / "deployment" / "ha-manifest.yaml"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


dump = yaml.safe_load(DUMP_PKG.read_text(encoding="utf-8"))
fp = yaml.safe_load(FP_PKG.read_text(encoding="utf-8"))

print("[1] Helper set and card/dashboard mapping")
helpers = {
    "armed": "input_boolean.ecco_dump_to_grid_schedule_armed",
    "start": "input_datetime.ecco_dump_to_grid_schedule_start",
    "duration": "input_number.ecco_dump_to_grid_schedule_duration",
    "power": "input_number.ecco_dump_to_grid_schedule_power",
    "stop_soc": "input_number.ecco_dump_to_grid_schedule_stop_soc",
    "last_result": "input_text.ecco_dump_to_grid_schedule_last_result",
    "cancel": "script.ecco_dump_to_grid_cancel_schedule",
}
defined = set()
for domain in ("input_boolean", "input_datetime", "input_number", "input_text", "script"):
    for key in (dump.get(domain) or {}):
        defined.add(f"{domain}.{key}")
for name, entity in helpers.items():
    check(f"package defines {entity}", entity in defined)
check("package defines the ECCO Dump to Grid Schedule Status template sensor (-> sensor.ecco_dump_to_grid_schedule_status)",
      any(s.get("name") == "ECCO Dump to Grid Schedule Status" for t in dump["template"] for s in t.get("sensor", [])))

dash = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))


def find_card(node):
    if isinstance(node, dict):
        if node.get("type") == "custom:ecco-energy-actions-card":
            return node
        for v in node.values():
            hit = find_card(v)
            if hit:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = find_card(v)
            if hit:
                return hit
    return None


card = find_card(dash)
dump_sched = (card or {}).get("dump_to_grid", {}).get("schedule", {})
for name, entity in helpers.items():
    check(f"dashboard card dump_to_grid.schedule.{name} maps to the package's {entity}", dump_sched.get(name) == entity,
          str(dump_sched.get(name)))
check("dashboard schedule status maps to sensor.ecco_dump_to_grid_schedule_status",
      dump_sched.get("status") == "sensor.ecco_dump_to_grid_schedule_status")

print("")
print("[2] Deployment manifest")
manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
sources = [p["source"] for p in manifest["home_assistant_packages"]]
dests = [p["destination"] for p in manifest["home_assistant_packages"]]
check("ha-manifest lists the Dump schedule package", "home-assistant/packages/ecco_dump_to_grid_schedule.yaml" in sources)
check("...deployed to /config/packages/ecco_dump_to_grid_schedule.yaml",
      "/config/packages/ecco_dump_to_grid_schedule.yaml" in dests)
check("...and the Free Power schedule package is still listed", "home-assistant/packages/ecco_free_power_schedule.yaml" in sources)

print("")
print("[3] No direct register-write path from Home Assistant")
text = DUMP_PKG.read_text(encoding="utf-8")
actions = set(re.findall(r"action:\s*([a-z_]+\.[a-z_]+)", text))
allowed = {"input_text.set_value", "number.set_value", "switch.turn_on", "switch.turn_off", "button.press",
           "input_boolean.turn_off", "script.ecco_dump_to_grid_start_scheduled"}
check("every service the package calls is staging/arm/press/helper-only", actions <= allowed, f"{sorted(actions - allowed)}")
check("no modbus/esphome raw-write services", not re.search(r"modbus\.|esphome\.|write_register", text))
check("the only firmware entities touched are the Dump staging numbers, the Dump write-enable and the Dump START button",
      set(re.findall(r"(?:number|switch|button)\.ecco_clock_dongle_\w+", text)) == {
          "number.ecco_clock_dongle_dump_to_grid_duration",
          "number.ecco_clock_dongle_dump_to_grid_export_power",
          "number.ecco_clock_dongle_dump_to_grid_stop_soc",
          "switch.ecco_clock_dongle_dump_to_grid_write_enable",
          "button.ecco_clock_dongle_start_dump_to_grid_now",
      })
# The recovery-action words are assembled from fragments on purpose: this
# file lives under home-assistant/, which registry/tests/
# test_free_power_recovery_evidence.py scans for those exact tokens (no HA
# file may reference a recovery-execute action).
RECOVERY_TOKENS = ("force_restore" + "_original", "accept" + "_current_state")
check("no HA package references the Dump recovery buttons (no automatic Force/Accept caller)",
      not any(any(tok in p.read_text(encoding="utf-8") for tok in RECOVERY_TOKENS)
              for p in (ROOT / "home-assistant" / "packages").glob("*.yaml")))

print("")
print("[4] Template behaviour - schedule overlap and TOU charging-slot refusal")


def arm_branches(pkg, automation_id):
    auto = next(a for a in pkg["automation"] if a["id"] == automation_id)
    choose = next(a["choose"] for a in auto["actions"] if "choose" in a)
    return auto, choose


def render(template: str, state: dict, variables: dict) -> str:
    env = jinja2.Environment()

    def states(entity_id):
        return state.get(entity_id, "unknown")

    def as_timestamp(value, default=None):
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return default

    env.globals.update(states=states, as_timestamp=as_timestamp,
                       is_state=lambda e, v: state.get(e) == v, namespace=jinja2.utils.Namespace)
    env.filters["timestamp_local"] = lambda ts: datetime.fromtimestamp(float(ts)).isoformat()
    env.tests["match"] = lambda value, pattern: re.match(pattern, str(value)) is not None
    return env.from_string(template).render(**variables).strip()


def branch_fires(branch, state, variables) -> bool:
    for cond in branch["conditions"]:
        if cond["condition"] == "state":
            if state.get(cond["entity_id"]) != cond["state"]:
                return False
        elif cond["condition"] == "template":
            if render(cond["value_template"], state, variables) != "True":
                return False
        else:
            raise AssertionError(cond)
    return True


_, dump_choose = arm_branches(dump, "ecco_dump_to_grid_schedule_arm_validation")
dump_overlap = next(b for b in dump_choose if "overlaps the armed Scheduled Free Power window" in str(b["sequence"]))
dump_slot = next(b for b in dump_choose if "charge source set" in str(b["sequence"]))
_, fp_choose = arm_branches(fp, "ecco_free_power_schedule_arm_validation")
fp_overlap = next(b for b in fp_choose if "overlaps the armed Scheduled Dump to Grid window" in str(b["sequence"]))


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


base = {
    "input_boolean.ecco_free_power_schedule_armed": "on",
    "input_datetime.ecco_free_power_schedule_start": "2026-09-27 17:00:00",
    "input_number.ecco_free_power_schedule_duration": "60",
    "input_boolean.ecco_dump_to_grid_schedule_armed": "on",
    "input_datetime.ecco_dump_to_grid_schedule_start": "2026-09-27 17:00:00",
    "input_number.ecco_dump_to_grid_schedule_duration": "30",
}
dump_vars = lambda start: {"start_ts": ts(start)}  # noqa: E731
check("Dump arm refused: same start minute as an armed Free Power schedule",
      branch_fires(dump_overlap, base, dump_vars("2026-09-27 17:00:00")))
check("Dump arm refused: starts inside the armed Free Power window",
      branch_fires(dump_overlap, {**base, "input_datetime.ecco_dump_to_grid_schedule_start": "2026-09-27 17:45:00"},
                   dump_vars("2026-09-27 17:45:00")))
check("Dump arm refused: ends within 2 minutes of the Free Power start (restore buffer)",
      branch_fires(dump_overlap, {**base, "input_datetime.ecco_dump_to_grid_schedule_start": "2026-09-27 16:29:00"},
                   dump_vars("2026-09-27 16:29:00")))
check("Dump arm allowed: well clear of the Free Power window",
      not branch_fires(dump_overlap, {**base, "input_datetime.ecco_dump_to_grid_schedule_start": "2026-09-27 19:00:00"},
                       dump_vars("2026-09-27 19:00:00")))
check("Dump arm allowed: Free Power schedule not armed",
      not branch_fires(dump_overlap, {**base, "input_boolean.ecco_free_power_schedule_armed": "off"},
                       dump_vars("2026-09-27 17:00:00")))
check("Free Power arm refused: overlaps an armed Dump schedule",
      branch_fires(fp_overlap, base, {"start_ts": ts("2026-09-27 17:00:00")}))
check("Free Power arm unaffected when the Dump package is absent (helper never 'on')",
      not branch_fires(fp_overlap, {k: v for k, v in base.items() if "dump_to_grid" not in k},
                       {"start_ts": ts("2026-09-27 17:00:00")}))

slots = {}
for i, (t, c) in enumerate([("00:00", "Grid"), ("05:30", "None"), ("08:00", "None"),
                            ("16:00", "None"), ("19:00", "None"), ("23:30", "None")], start=1):
    slots[f"sensor.ecco_clock_dongle_ecco_timezone{i}_time"] = t
    slots[f"sensor.ecco_clock_dongle_ecco_timezone{i}_charge"] = c


def slot_hit(start, duration, extra=None):
    state = {**slots, "input_number.ecco_dump_to_grid_schedule_duration": str(duration), **(extra or {})}
    return branch_fires(dump_slot, state, {"start_ts": ts(start)})


check("slot check: 02:00 (inside the slot-1 grid-charge window) refused", slot_hit("2026-09-27 02:00:00", 10))
check("slot check: 23:50 + 30 min (crosses midnight into slot 1) refused", slot_hit("2026-09-27 23:50:00", 30))
check("slot check: 14:00 + 60 min (slot 3, no charge source) allowed", not slot_hit("2026-09-27 14:00:00", 60))
check("slot check: 23:00 + 20 min (ends before 00:00) allowed", not slot_hit("2026-09-27 23:00:00", 20))
check("slot check: slot sensors unavailable -> does not refuse (defers to the firmware's own START check)",
      not slot_hit("2026-09-27 02:00:00", 10, {"sensor.ecco_clock_dongle_ecco_timezone3_time": "unavailable"}))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print(f"  - {n}")
else:
    print("All Scheduled Dump to Grid package checks PASSED.")
print("")
print("NOTE: jinja2 with stand-in HA helpers is not Home Assistant itself - only `ha core check` plus live")
print("observation can prove the templates render identically there. This package remains STAGED / NOT LIVE-PROVEN.")
if FAILURES:
    sys.exit(1)
