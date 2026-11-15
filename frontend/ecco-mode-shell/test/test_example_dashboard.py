#!/usr/bin/env python3
"""AC16 (example side): examples/intelligence-modes.yaml wraps the EXISTING ECCO Intelligence dashboard's cards in the Mode Shell
WITHOUT changing them.

  [1] the existing dashboard (home-assistant/dashboards/ecco_intelligence.yaml) and the example parse (the example's
      `catalogue: !include ...` is data, kept as a tagged scalar)
  [2] the shell is the first card; `always` holds the Intelligence card and the watchdog / status entities card, each EQUAL to the
      existing dashboard's configuration; `production` holds the pause tile, EQUAL to the existing one (same toggle actions: the
      same permissions in both modes); the markdown text fallback is EQUAL and sits outside the shell
  [3] the always list is read-only by the shell's own rule: no action other than none / more-info / navigate, no service call, no
      write-capable card type, no entities row of a writable domain (this mirrors validateChildCards)
  [4] the only write action anywhere in the example is the existing pause tile's toggle, and it is in `production`
  [5] the shell card carries no service call, script or perform-action of its own

Test-only, no network, no Node. I/O: reads two repository files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
EXISTING = ROOT / "home-assistant" / "dashboards" / "ecco_intelligence.yaml"
EXAMPLE = ROOT / "frontend" / "ecco-mode-shell" / "examples" / "intelligence-modes.yaml"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class Loader(yaml.SafeLoader):
    """Safe loader that keeps `!include x` as the text 'x' (the include target is data, resolved by Home Assistant)."""


Loader.add_constructor("!include", lambda loader, node: f"!include {loader.construct_scalar(node)}")


def load(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)  # noqa: S506 - SafeLoader subclass


SAFE_ACTIONS = {"none", "more-info", "navigate"}
WRITE_TYPES = {"button", "entity-button", "light", "thermostat", "humidifier", "media-control", "alarm-panel", "shopping-list", "todo-list", "iframe", "webpage"}
WRITABLE_DOMAINS = {"switch", "light", "input_boolean", "fan", "cover", "lock", "climate", "automation", "script", "scene", "button", "input_button", "select",
                    "input_select", "number", "input_number", "input_datetime", "input_text", "text", "humidifier", "valve", "vacuum", "water_heater",
                    "media_player", "siren", "update", "remote", "alarm_control_panel", "lawn_mower", "datetime", "date", "time"}


def write_findings(node, path="card") -> list[str]:
    """Mirror of validateChildCards for the cards used here."""
    out: list[str] = []
    if isinstance(node, list):
        for i, x in enumerate(node):
            out += write_findings(x, f"{path}[{i}]")
        return out
    if not isinstance(node, dict):
        return out
    if node.get("type") in WRITE_TYPES:
        out.append(f"{path}: write-capable type {node['type']}")
    if "action" in node and node["action"] not in SAFE_ACTIONS:
        out.append(f"{path}: action {node['action']}")
    for k, v in node.items():
        if k in {"service", "service_data", "perform_action", "call-service"}:
            out.append(f"{path}.{k}: service call")
        if k == "entities" and node.get("type") == "entities":
            for i, row in enumerate(v):
                eid = row if isinstance(row, str) else (row.get("entity", "") if isinstance(row, dict) else "")
                if eid.split(".")[0] in WRITABLE_DOMAINS:
                    out.append(f"{path}.entities[{i}]: writable row {eid}")
        out += write_findings(v, f"{path}.{k}")
    return out


def main() -> int:
    print("[1] both files parse")
    existing = load(EXISTING)
    example = load(EXAMPLE)
    check("the existing dashboard parses and has one view", isinstance(existing, dict) and len(existing["views"]) == 1)
    check("the example parses and has one view", isinstance(example, dict) and len(example["views"]) == 1)
    ecards = existing["views"][0]["cards"]
    xcards = example["views"][0]["cards"]
    intel, tile, entities, markdown = ecards[0], ecards[1], ecards[2], ecards[3]

    print("[2] the existing cards are wrapped, not changed")
    shell = xcards[0]
    check("the first card is the shell", shell.get("type") == "custom:ecco-mode-shell")
    check("the shell includes its catalogue as data", isinstance(shell.get("catalogue"), str) and shell["catalogue"].startswith("!include "))
    check("always holds exactly the Intelligence card and the entities card", len(shell["always"]) == 2)
    check("the Intelligence card is unchanged", shell["always"][0] == intel, f"{shell['always'][0]} != {intel}")
    check("the watchdog / status entities card is unchanged", shell["always"][1] == entities)
    check("production holds exactly the pause tile", len(shell["production"]) == 1)
    check("the pause tile is unchanged (same toggle, same hold action)", shell["production"][0] == tile, f"{shell['production'][0]} != {tile}")
    check("the text fallback is unchanged and sits outside the shell", len(xcards) == 2 and xcards[1] == markdown)
    check("the example view keeps the existing view's title, path and icon",
          all(example["views"][0][k] == existing["views"][0][k] for k in ("title", "path", "icon")))

    print("[3] the always list is read-only")
    findings = write_findings(shell["always"])
    check("no write finding in always", findings == [], "; ".join(findings))
    check("the Intelligence card's configuration has no action of any kind", "action" not in repr(shell["always"][0]).replace("tap_action", ""))
    check("the negative control: the pause tile WOULD be refused in always", write_findings([tile]) != [])

    print("[4] the only write action is the existing pause tile's toggle, in production")
    check("the pause tile toggles input_boolean.ecco_intel_paused",
          tile["entity"] == "input_boolean.ecco_intel_paused" and tile["tap_action"]["action"] == "toggle" and tile["icon_tap_action"]["action"] == "toggle")
    all_findings = write_findings(xcards[0].get("always", [])) + write_findings(xcards[1:])
    check("nothing outside production carries a write action", all_findings == [], "; ".join(all_findings))
    text = EXAMPLE.read_text(encoding="utf-8")
    check("toggle appears only in the pause tile's two actions (and in prose comments)",
          sum(1 for line in text.splitlines() if line.strip() == "action: toggle") == 2)

    print("[5] the shell has no write path of its own")
    check("no service, perform_action or script key on the shell", not any(k in shell for k in ("service", "perform_action", "script", "tap_action", "hold_action")))
    check("the only keys the shell is given are the documented ones", set(shell) == {"type", "view_id", "title", "catalogue", "always", "production"}, str(sorted(shell)))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All example-dashboard checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
