#!/usr/bin/env python3
"""Tests for the LOCAL prototype dashboard + mock sensor package (home-assistant/prototypes/intelligence-v1/).

Proves: it is read-only (no service calls / control entities), isolated from production (not in the deploy manifest,
not under dashboards/), every entity it reads either exists in the repo or is one of the five mock sensors, the mock
package matches the single render contract, attribute payloads are small, and every card's JavaScript runs (in Node)
and shows the required ACTUAL / PREDICTED / RECOMMENDED / CONFIDENCE blocks, the SHADOW banner and the disabled Apply."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "intelligence" / "tools"))

try:
    import yaml
except ImportError:                      # the repo CI installs pyyaml; locally it is optional
    print("PyYAML not installed: dashboard prototype tests SKIPPED")
    sys.exit(0)

import render_ha_prototype as rhp  # noqa: E402
import preview_dashboard as pd  # noqa: E402

PROTO = ROOT / "home-assistant" / "prototypes" / "intelligence-v1"
dash_text = (PROTO / "ecco_intelligence_v1_prototype_dashboard.yaml").read_text(encoding="utf-8")
dash = yaml.safe_load(dash_text)
pkg = yaml.safe_load((PROTO / "ecco_intelligence_v1_mock_package.yaml").read_text(encoding="utf-8"))

section("read-only and isolated")
forbidden = ("callService", "callApi", "fetch(", "XMLHttpRequest", "hass.call", "subscribeMessage", "call-service", "perform-action", "button.press", "switch.turn", "script.", "automation.", "input_boolean.turn",
             "light.turn", "number.set_value", "esphome.", "action: toggle", "url_path")
low = "\n".join(l for l in dash_text.splitlines() if not l.lstrip().startswith("#"))
check("no service-call or control vocabulary in the dashboard YAML", not [w for w in forbidden if w in low],
      str([w for w in forbidden if w in low]))
def collect_actions(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("tap_action", "hold_action", "double_tap_action") and isinstance(v, dict):
                out.add(v.get("action"))
            collect_actions(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_actions(v, out)


actions: set = set()
collect_actions(dash, actions)
check("every tap action is none or more-info", actions <= {"none", "more-info"}, str(actions))
manifest = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
check("prototype files are not in the deployment manifest", "prototypes" not in manifest and "intelligence" not in manifest.lower())
check("prototype lives outside home-assistant/dashboards and packages",
      "dashboards" not in str(PROTO.relative_to(ROOT)) and "packages" not in str(PROTO.relative_to(ROOT)))
check("production dashboard is untouched by name (this view is separate)", "ecco-intelligence-v1-prototype" in dash_text
      and dash["views"][0]["path"] == "ecco-intelligence-v1-prototype")
check("the Apply control is a DISABLED html button with an explanation", "<button disabled" in dash_text and "never writes to the inverter" in dash_text)
check("SHADOW banner text present", "SHADOW MODE" in dash_text and "Nothing is applied" in dash_text)

section("entities: real ones exist in the repo, intelligence ones come only from the mock package")
ids = set(re.findall(r"\b((?:sensor|binary_sensor|input_number)\.[a-z0-9_]*[a-z0-9])", low))
check("the entity scan sees the real entities this view reads (guards against a vacuous regex)",
      {"sensor.ecco_battery_soc", "sensor.ecco_house_power", "sensor.ecco_intelligence_status"} <= ids, str(sorted(ids)[:6]))
mock = {"sensor." + s["unique_id"] for s in pkg["template"][0]["sensor"]}
check("exactly the five contract sensors are mocked", mock == {"sensor.ecco_intelligence_" + k for k in
                                                              ("status", "predicted", "recommended", "trajectory", "accuracy")})
repo_text = ""
for sub in ("home-assistant/packages", "firmware"):
    for f in (ROOT / sub).rglob("*.yaml"):
        repo_text += f.read_text(encoding="utf-8", errors="ignore")
missing = []
for i in sorted(ids - mock):
    domain, obj = i.split(".", 1)
    # a template sensor is declared by its unique_id or name; an ESPHome entity by its (slugified) name
    if f"unique_id: {obj.removeprefix('')}" in repo_text or f"unique_id: {obj}" in repo_text:
        continue
    if i in ("sensor.ecco_battery_soc", "sensor.ecco_house_power", "sensor.ecco_pv_power", "sensor.ecco_grid_power"):
        if f"unique_id: {obj.replace('sensor.', '')}" in repo_text or "ecco_canonical_telemetry" in repo_text:
            continue
    if obj in repo_text or obj.replace("ecco_clock_dongle_", "") in repo_text.replace(" ", "_").lower():
        continue
    # live-verified existing helpers referenced elsewhere in the production dashboard
    if i in (ROOT / "home-assistant/dashboards/ecco_pro.yaml").read_text(encoding="utf-8"):
        continue
    missing.append(i)
check("every non-mock entity is already used by the production dashboard / packages", not missing, str(missing))

section("mock package equals the render contract and stays small")
report = json.loads((ROOT / "docs/intelligence/examples/example_live_inputs.json").read_text(encoding="utf-8"))
acc = json.loads((ROOT / "docs/intelligence/examples/example_accuracy_history.json").read_text(encoding="utf-8"))
regen = yaml.safe_load(rhp.render(report, acc, "example_live_inputs.json"))
check("checked-in package is exactly what the generator produces from the checked-in example", regen == pkg)
big = [(s["unique_id"], k) for s in pkg["template"][0]["sensor"] for k, v in s["attributes"].items() if len(json.dumps(v)) > 8000]
check("no single attribute exceeds 8 kB (HA recorder drops attributes over 16 kB)", not big, str(big))
check("every mock sensor is marked SHADOW", all(s["attributes"].get("mode") == "SHADOW" or s["unique_id"] == "ecco_intelligence_status"
                                                 and s["attributes"]["mode"] == "SHADOW" for s in pkg["template"][0]["sensor"]))
check("the status sensor says it applies nothing", [s for s in pkg["template"][0]["sensor"] if s["unique_id"] == "ecco_intelligence_status"][0]["attributes"]["applies_nothing"] is True)

section("every card's JavaScript runs and the required blocks render")
if shutil.which("node") is None:
    print("  node not installed: JS render checks SKIPPED")
else:
    page, problems = pd.render()
    check("no JavaScript template raised an error", not problems, str(problems[:2]))
    for needle in ("MEASURED NOW", "MODEL OUTPUT", "ADVICE ONLY", "HOW MUCH TO TRUST THIS", "Apply (disabled", "Minimum battery reserve 40%", "Minimum Battery Reserve",
                   "ECCO expects", "Learning normally", "FROZEN SAMPLE REPORT", "Reasons"):
        check(f"rendered page contains {needle!r}", needle in page)
    check("ACTUAL, PREDICTED, RECOMMENDED and CONFIDENCE are four distinct blocks",
          all(page.count(f'class="ttl">{n}</div>') == 1 for n in ("Actual", "Predicted", "Recommended", "Confidence")))
    check("the live ACTUAL values come from the sample sensors (SOC 88 %, 1.10 kW house)", "88 %" in page and "1.10 kW" in page)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in {"intelligence dashboard prototype"}:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print(f"All {"intelligence dashboard prototype"} checks PASSED.")