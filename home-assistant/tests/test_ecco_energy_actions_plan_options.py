#!/usr/bin/env python3
"""ovw4: the Overview's Energy Actions card carries the Stage 3 plan options in the repository's own dashboard (offline, stdlib + PyYAML).

Proves (display configuration only; nothing here proves behaviour on a real Home Assistant):
  1. the two edits of registry/tests/_ovw4_scope.py are exact: they apply once, revert once and round-trip on the dashboard text;
  2. the dashboard has exactly ONE Energy Actions card and it sets show_plan, plan.entity_prefix / plan.reserve and
     dump_to_grid.guarded_start, with the repository's GENERIC values (the default device slug in quotes, never a site value);
  3. every entity the new lines name is defined by a package of this repository (the reserve helper, the guarded start script);
  4. the card's own config reader knows the three options (its source names them);
  5. the protected layer is untouched: the Overview's flow card (/views/0/sections/2/cards/0) and every card but the one are
     byte-identical once ovw4 is undone.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "registry" / "tests"))
import _ovw4_scope as S  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"   [{detail}]"))
    if not ok:
        FAILURES.append(name)


def cards(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("type") == "custom:ecco-energy-actions-card":
            out.append(node)
        for v in node.values():
            cards(v, out)
    elif isinstance(node, list):
        for v in node:
            cards(v, out)
    return out


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _raises(fn, text) -> bool:
    try:
        fn(text)
    except AssertionError:
        return True
    return False


live = (REPO / S.DASHBOARD_REL).read_text(encoding="utf-8")
pre = S.pre_ovw4_dashboard(live)
check("the reverter removes the edits and the round trip restores the text exactly", S.add_ovw4_dashboard(pre) == live)
check("each edit adds text and every anchor is unique in the earlier text",
      all(a != b and pre.count(a) == 1 for a, b in S.DASHBOARD_EDITS))
check("an edited-twice or edit-free text is refused", all(_raises(f, t) for f, t in
      ((S.pre_ovw4_dashboard, pre), (S.add_ovw4_dashboard, live))))
d = yaml.safe_load(live)
found = cards(d)
check("the dashboard has exactly one Energy Actions card", len(found) == 1, str(len(found)))
c = found[0]
check("show_plan is true", c.get("show_plan") is True)
check("plan.entity_prefix is the generic default device slug (rendered per site, like the TOU Settings card)",
      (c.get("plan") or {}).get("entity_prefix") == "ecco_clock_dongle")
check("plan.reserve is the reserve helper", (c.get("plan") or {}).get("reserve") == "input_number.ecco_minimum_reserve_soc")
check("dump_to_grid.guarded_start is the guarded start script",
      (c.get("dump_to_grid") or {}).get("guarded_start") == "script.ecco_dump_to_grid_start_guarded")
new_text = "".join(a + b for a, b in S.DASHBOARD_EDITS)
check("no site value in the new lines (the only device slug is the generic default, quoted; no address)",
      re.findall(r"[a-z0-9_]*ecco_clock_dongle[a-z0-9_]*", new_text) == ["ecco_clock_dongle"] and '"ecco_clock_dongle"' in new_text
      and not re.search(r"192\.168|\b10\.\d+\.\d+\.\d+", new_text))
pk = "\n".join(p.read_text(encoding="utf-8") for p in sorted((REPO / "home-assistant" / "packages").glob("*.yaml")))
check("the guarded start script is defined by a package", re.search(r"^  ecco_dump_to_grid_start_guarded:", pk, re.M) is not None)
check("the reserve helper is defined by a package or named by the battery policy package",
      "input_number.ecco_minimum_reserve_soc" in pk)
src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((REPO / "frontend" / "ecco-energy-actions-card" / "src").glob("*.ts")))
check("the card's source reads show_plan, plan.entity_prefix, plan.reserve and guarded_start",
      all(k in src for k in ("show_plan", "entity_prefix", "guarded_start")) and "reserve" in src)
a, b = yaml.safe_load(pre), d
check("the protected layer (the Overview's flow card) is byte-identical to its state before ovw4",
      canon(a["views"][0]["sections"][2]["cards"][0]) == canon(b["views"][0]["sections"][2]["cards"][0]))
ea = found[0]
stripped = {k: v for k, v in ea.items() if k not in ("show_plan", "plan")}
stripped["dump_to_grid"] = {k: v for k, v in ea["dump_to_grid"].items() if k != "guarded_start"}
pc = cards(a)[0]
check("with the three options removed the card is exactly the card before ovw4", canon(stripped) == canon(pc))
check("the dashboard has the same views and sections as before ovw4",
      [len(v.get("sections", [])) for v in a["views"]] == [len(v.get("sections", [])) for v in b["views"]])

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("All ovw4 (Energy Actions plan options) checks passed.")
print("These prove the dashboard text and its exact edits; they prove nothing about a real Home Assistant.")
