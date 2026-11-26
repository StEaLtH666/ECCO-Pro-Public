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
  [6] the example's `!include` points at the REAL catalogue of this repository (a relative path that stays inside the repository), the
      file is what Home Assistant would load (a YAML loader that resolves the include reads exactly what a JSON loader reads), and it is
      the catalogue of this view (schema, view id, a source for every entity the wrapped cards use)

Test-only, no network, no Node. I/O: reads two repository files.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
EXISTING = ROOT / "home-assistant" / "dashboards" / "ecco_intelligence.yaml"
EXAMPLE = ROOT / "frontend" / "ecco-mode-shell" / "examples" / "intelligence-modes.yaml"
CATALOGUE = ROOT / "frontend" / "ecco-mode-shell" / "catalogue" / "intelligence.catalogue.json"

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


def resolve_include(spec: str, base: Path) -> Path:
    """Where Home Assistant looks for `!include <spec>`: relative to the YAML file that holds the tag."""
    return (base.parent / spec[len("!include "):]).resolve()


def make_including_loader(base: Path):
    """A safe loader that RESOLVES `!include` the way Home Assistant does (the included file is read by the same YAML loader)."""

    class Including(yaml.SafeLoader):
        pass

    def construct(loader, node):
        target = resolve_include("!include " + loader.construct_scalar(node), base)
        return yaml.load(target.read_text(encoding="utf-8"), Loader=Including)  # noqa: S506 - SafeLoader subclass

    Including.add_constructor("!include", construct)
    return Including


def entity_ids_used(cards) -> set[str]:
    """Every entity id a wrapped card names: the Intelligence card's map, entities rows, tile, and the text fallback's template."""
    out: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "entity" and isinstance(v, str):
                    out.add(v)
                elif k == "entities" and isinstance(v, dict):
                    out.update(x for x in v.values() if isinstance(x, str))
                elif k == "content" and isinstance(v, str):
                    out.update(re.findall(r"\b(?:sensor|binary_sensor|input_boolean)\.ecco_intel_[a-z_]+\b", v))
                    out.update(re.findall(r"'((?:sensor|binary_sensor|input_boolean)\.ecco_intel_[a-z_]+)'", v))
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(cards)
    return out


SAFE_ACTIONS = {"none", "more-info", "navigate"}
# the card types the shell lets into a Geek-visible region (mirror of ALLOWED_CARD_TYPES and the default custom cards in ecco-mode-shell.js)
ALLOWED_CARD_TYPES = {"markdown", "entities", "glance", "history-graph", "statistics-graph", "sensor", "gauge", "entity", "heading", "vertical-stack",
                      "horizontal-stack", "grid", "conditional", "tile"}
DEFAULT_CUSTOM_CARDS = {"custom:ecco-intelligence-card"}
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
    types = [c.get("type") for c in shell["always"]]
    check("every card type in always is on the shell's allowlist (a type the shell does not know is refused, so the example must not use one)",
          all(t in ALLOWED_CARD_TYPES or t in DEFAULT_CUSTOM_CARDS for t in types), str(types))
    check("the example needs no allow_custom_cards: its one custom card is on the default list", "allow_custom_cards" not in shell and "custom:ecco-intelligence-card" in types)
    check("the negative control: a picture-glance, an area and a custom button card are not on the allowlist",
          not any(t in ALLOWED_CARD_TYPES or t in DEFAULT_CUSTOM_CARDS for t in ("picture-glance", "area", "custom:button-card")))

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

    print("[6] the include points at the real catalogue")
    spec = shell["catalogue"]
    target = resolve_include(spec, EXAMPLE)
    check("the include is a relative path (no absolute path, no drive, no URL)",
          not spec.split(" ", 1)[1].startswith(("/", "\\")) and "://" not in spec and ":" not in spec.split(" ", 1)[1], spec)
    check("it resolves to frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json, inside the repository",
          target == CATALOGUE.resolve() and ROOT.resolve() in target.parents, str(target))
    check("the included file exists and is a regular file", target.is_file() and not target.is_symlink())
    real = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    resolved = yaml.load(EXAMPLE.read_text(encoding="utf-8"), Loader=make_including_loader(EXAMPLE))  # noqa: S506 - SafeLoader subclass
    included = resolved["views"][0]["cards"][0]["catalogue"]
    check("a YAML loader that resolves the include reads exactly what a JSON loader reads (JSON is YAML here)", included == real)
    check("the resolved catalogue is the agreed schema and this view's", included["schema"] == "ecco-geek-catalogue/1" and included["view_id"] == shell["view_id"])
    check("the shell's own title and view id match the catalogue's view", shell["view_id"] == "intelligence")
    sources = {x["entity_id"] for x in real["sources"]}
    used = entity_ids_used(resolved["views"][0]["cards"])
    check("the wrapped cards name at least the thirteen entities of the Intelligence card", len(used) >= 13, str(sorted(used)))
    check("every entity a wrapped card uses is a source of the catalogue (so Geek Mode shows everything Production uses)",
          used <= sources, str(sorted(used - sources)))
    check("the resolved cards are still equal to the existing dashboard's (the include changed nothing else)",
          resolved["views"][0]["cards"][0]["always"] == [intel, entities] and resolved["views"][0]["cards"][0]["production"] == [tile])

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
