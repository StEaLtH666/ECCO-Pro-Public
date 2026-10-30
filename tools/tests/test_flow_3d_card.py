#!/usr/bin/env python3
"""Regression suite: the ECCO 3D Energy Flow card (frontend/ecco-flow-3d-card, read-only; on the production dashboard's Overview since
post-export entry ovw3, dashboard 7.23.0, staged).

  [1] the card folder: the expected files only, package / lock / hacs metadata, text files only, LF
  [2] read-only allowlist over the source and the committed bundle: no service / action / websocket / network / storage /
      dynamic-code API; the only dispatched event is Home Assistant's own hass-more-info; the two timers it does use are the
      15 s clock refresh and the particle and link-pulse animation frame; no fetch, no import() of anything
  [3] no reserved fallback / shadow token in any card file
  [4] the example's entity ids are the repository's own (packages, dashboard, canonical aliases, firmware sensor names; the dashboard's
      own copy of the card's configuration does not count, and that exclusion fails closed: exactly one block, from the dashboard,
      parsing back to the dashboard's own card); the sign conventions match the installed Energy Flow card's example
  [5] routing is isolated data: src/scene/routing-v4.ts imports nothing from the telemetry, motion or Lit layers
  [6] the site renderer renders the bundle and the example (and not the sources or tests)
  [7] the card's Node suite (node --test, TAP), when the host Node can run TypeScript tests (22.18+); otherwise reported as skipped.
      Only the two deterministic-rebuild tests may skip, and only where esbuild is not installed, and the three card-link rendering
      tests, and only where Lit is not installed (CI installs no npm package)
  [8] scope and integration (ovw3): the card is in no manifest, package, version-file line or other dashboard; the production
      dashboard uses it exactly once, as the one card of Overview section S3 in place of the 2D Energy Flow card, configured as its
      example (the ECCO 3D Preview's configuration) plus the dashboard's grid layout (no card_mod); the ovw3 chain entry declares
      exactly the dashboard and VERSION.yaml; INSTALL_PREVIEW.md names the rollback and the production placement

The card's behaviour (power model parity with the Energy Flow card, directions, idle / unknown / stale, motion curve, FE-1,
sessions, TOU, health, scenes, layout geometry, build determinism) is tested by its Node suite: frontend/ecco-flow-3d-card/test.

Test-only, no network. I/O: reads repo files; runs node (if present) on the card's own tests.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ecco_site_render as R  # noqa: E402

CARD = ROOT / "frontend" / "ecco-flow-3d-card"
TAG = "ecco-flow-3d-card"
DIST = CARD / "dist" / f"{TAG}.js"
EXAMPLE = CARD / "examples" / "ecco-example.yaml"
SRC = CARD / "src"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def card_files() -> list[str]:
    return sorted(p.relative_to(CARD).as_posix() for p in CARD.rglob("*") if p.is_file() and "node_modules" not in p.parts)


def code_only(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"(^|[^:\"'`])//.*$", r"\1", text, flags=re.M)


# ===========================================================================
print("[1] the card folder")
# ===========================================================================
EXPECTED = {
    "INSTALL_PREVIEW.md", "README.md", "build.mjs", "hacs.json", "package-lock.json", "package.json", "tsconfig.json",
    f"dist/{TAG}.js", "examples/ecco-example.yaml",
    "preview/capture.ps1", "preview/index.html", "preview/mock.js", "preview/serve.mjs",
    "src/config.ts", "src/ecco-flow-3d-card.ts",
    "src/core/format.ts", "src/core/motion.ts", "src/core/power.ts", "src/core/scenes.ts", "src/core/status.ts",
    "src/scene/icons.ts", "src/scene/iso.ts", "src/scene/perspective.ts", "src/scene/routing-v4.ts", "src/scene/scene.ts",
    "test/artworkLayout.test.ts", "test/build.test.ts", "test/flow.test.ts", "test/geometry.test.ts", "test/links.test.ts", "test/motion.test.ts",
    "test/parity.test.ts", "test/safety.test.ts", "test/scenes.test.ts", "test/sensorMapping.test.ts", "test/status.test.ts",
}
files = card_files()
check("the card folder holds exactly the expected files (sources, tests, dist, example, preview harness, docs, metadata)",
      set(files) == EXPECTED, f"extra {sorted(set(files) - EXPECTED)} missing {sorted(EXPECTED - set(files))}")
raw = {f: (CARD / f).read_bytes() for f in files}
binary = [f for f, b in raw.items() if b"\0" in b]
crlf = [f for f, b in raw.items() if b"\r\n" in b]
check("text files only (no binary), LF line endings", not binary and not crlf, f"{binary} {crlf}")
pkg = json.loads(raw["package.json"])
lock = json.loads(raw["package-lock.json"])
check("package.json: private, module, GPL-3.0-or-later, lit the only runtime dependency, esbuild / typescript dev pins",
      pkg.get("private") is True and pkg.get("type") == "module" and pkg.get("license") == "GPL-3.0-or-later"
      and list(pkg.get("dependencies", {})) == ["lit"] and set(pkg.get("devDependencies", {})) == {"esbuild", "typescript"})
check("package-lock.json v3 agrees (root name, licence) and resolves esbuild 0.28.1",
      lock.get("lockfileVersion") == 3 and lock["packages"][""].get("name") == TAG and lock["packages"][""].get("license") == "GPL-3.0-or-later"
      and lock["packages"].get("node_modules/esbuild", {}).get("version") == "0.28.1")
hacs = json.loads(raw["hacs.json"])
check("hacs.json names the built file", hacs.get("filename") == f"{TAG}.js" and hacs.get("content_in_root") is False)

# ===========================================================================
print("")
print("[2] read-only allowlist (source and bundle)")
# ===========================================================================
FORBIDDEN = ["callService", "callWS", "callApi", "fetchWithAuth", "subscribeEvents", "subscribeMessage", "sendMessagePromise",
             "perform_action", "return_response", "call_service", "execute_script", "fire_event", "subscribe_events",
             "subscribe_trigger", "render_template", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "localStorage",
             "sessionStorage", "indexedDB", "postMessage", "document.cookie", "hass-action", "button.press", "switch.turn_",
             "number.set_value", "select.select_option", "modbus", "esphome."]
FORBIDDEN_RE = [r"\bfetch\s*\(", r"\beval\s*\(", r"\bnew\s+Function\s*\(", r"\bimport\s*\(", r"https?://(?!lit\.dev|github\.com|opensource\.org|www\.w3\.org|polymer\.github\.io)"]
sources = {p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.ts"))}
dist = DIST.read_text(encoding="utf-8")
for name, text in sources.items():
    bad = [t for t in FORBIDDEN if t in text] + [r for r in FORBIDDEN_RE if re.search(r, text)]
    check(f"src/{name}: no service, action, websocket, network, storage or dynamic-code API", not bad, str(bad))
alls = "\n".join(code_only(t) for t in sources.values())
events = sorted(set(re.findall(r"new CustomEvent\(\"([^\"]+)\"", alls)))
check("the only event the card dispatches is hass-more-info (Home Assistant's own more-info request)", events == ["hass-more-info"], str(events))
timers = re.findall(r"\b(setInterval|setTimeout|requestAnimationFrame)\s*\(", alls)
check("timers: the 15 s clock refresh, the crossfade settle timeout and the particle and link-pulse animation frame, nothing else",
      sorted(set(timers)) == ["requestAnimationFrame", "setInterval", "setTimeout"] and timers.count("setInterval") == 1, str(sorted(set(timers))))
card_src = code_only(sources.get(f"{TAG}.ts", ""))
check("the element reads hass.states only and never assigns hass or a connection to itself",
      not re.search(r"\bhass\??\.(?!states\b)[A-Za-z_]", card_src) and not re.search(r"this\.(?:_?hass|_?connection|_?conn)\s*=", card_src))
bad = [t for t in FORBIDDEN if t in dist] + [r for r in FORBIDDEN_RE if re.search(r, dist)]
check("the bundle names no forbidden API and loads nothing external", not bad, str(bad))
check("the bundle is self-contained: no import, no require, no source map, no local path",
      not re.search(r"(?:^|[;\n])\s*import\s*[\s{*\"']", dist) and "require(" not in dist and "sourceMappingURL" not in dist
      and not re.search(r"[A-Za-z]:\\|/Users/|/home/|node_modules", dist))

# ===========================================================================
print("")
print("[3] reserved tokens")
# ===========================================================================
FB, FL = "fail" + "back", "fall" + "back"
RESERVED = re.compile("|".join([f"ecco_{FL}", f"{FL.upper()}_PROFILE", f"{FB.upper()}_STATE", f"ecco_{FB}", "ecco_" + "shadow_",
                                "Shadow " + "Recovery", f"{FB}_shadow", "fbc" + "_raw_", f"{FL}_profile_live" + "_match"]))
hits = [f for f in files if RESERVED.search(raw[f].decode("utf-8", "replace"))]
check("no card file spells a reserved fallback / shadow token", not hits, str(hits))

# ===========================================================================
print("")
print("[4] the example's entities are the repository's own")
# ===========================================================================
example = EXAMPLE.read_text(encoding="utf-8")
ids = sorted(set(re.findall(r"\b(?:sensor|binary_sensor|sun|weather|input_[a-z]+|switch|number|select)\.[a-z0-9_]+", example)))


def without_card_blocks(text: str) -> tuple[str, list[str]]:
    """The text without each block-style YAML list item whose first line is `- type: custom:<TAG>` (that line and every blank or
    deeper-indented line after it), and the removed blocks: the production dashboard's copy of the card's configuration (ovw3) must not
    prove the example's own ids. Line-ending safe. The check after the corpus makes this fail closed."""
    out, blocks, skip = [], [], None
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if skip is not None and (not line.strip() or indent > skip):
            blocks[-1].append(line)
            continue
        skip = None
        if line.strip() == f"- type: custom:{TAG}":
            skip = indent
            blocks.append([line])
            continue
        out.append(line)
    return "\n".join(out), ["\n".join(b) + "\n" for b in blocks]


REMOVED: dict[str, list[str]] = {}   # repo-relative file -> the card blocks left out of the corpus


def corpus_text() -> str:
    parts = []
    for d in ("home-assistant", "registry", "docs"):
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file() and p.suffix in {".yaml", ".yml", ".md", ".json"}:
                text, blocks = without_card_blocks(p.read_text(encoding="utf-8", errors="replace"))
                if blocks:
                    REMOVED[p.relative_to(ROOT).as_posix()] = blocks
                parts.append(text)
    for p in (ROOT / "frontend").rglob("*"):
        if p.is_file() and p.suffix in {".yaml", ".ts", ".md"} and "node_modules" not in p.parts and not str(p).startswith(str(CARD)):
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


corpus = corpus_text()
DASH_REL = "home-assistant/dashboards/ecco_pro.yaml"
dash_text = (ROOT / DASH_REL).read_text(encoding="utf-8")
dash = yaml.safe_load(dash_text)
dash_cards = [c for v in dash.get("views", []) for s in (v.get("sections", []) or []) for c in (s.get("cards", []) or [])
              if isinstance(c, dict) and c.get("type") == f"custom:{TAG}"]
dash_stripped, dash_blocks = without_card_blocks(dash_text)
check("the corpus leaves out exactly the dashboard's one copy of the card's configuration, and all of it (fails closed): one block, from "
      "the dashboard only, parsing back to exactly the dashboard's own card, and no `type: custom:` use of the card left in the stripped "
      "dashboard",
      set(REMOVED) == {DASH_REL} and len(REMOVED[DASH_REL]) == 1 and dash_blocks == REMOVED[DASH_REL] and len(dash_cards) == 1
      and yaml.safe_load(textwrap.dedent(dash_blocks[0])) == dash_cards and f"type: custom:{TAG}" not in dash_stripped
      and f"type: custom:{TAG}" in dash_text, str({k: len(v) for k, v in REMOVED.items()}))
firmware = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "firmware").glob("*.yaml"))
slugs = {"ecco_clock_dongle_" + re.sub(r"_+$", "", re.sub(r"^_+", "", re.sub(r"[^a-z0-9]+", "_", m.lower())))
         for m in re.findall(r"^\s+name:\s*\"?([^\"\n]+?)\"?\s*$", firmware, re.M)}
missing = [i for i in ids if i not in corpus and i.split(".", 1)[1] not in slugs]
check(f"every one of the {len(ids)} entity ids in examples/ecco-example.yaml exists elsewhere in the repository", not missing and len(ids) >= 60, str(missing))
installed = (ROOT / "frontend" / "ecco-energy-flow-card" / "examples" / "ecco-example.yaml").read_text(encoding="utf-8")
check("sign conventions and canonical sources match the installed Energy Flow card's example",
      all(line in example and line in installed for line in ("power_sign: discharge_positive", "power_sign: import_positive",
                                                                "power: sensor.ecco_grid_power", "power: sensor.ecco_house_power",
                                                                "solar_total: sensor.ecco_pv_power")))
check("the example configures no time-to-charge-target entity (ECCO has none; the card shows it as not available)",
      not re.search(r"^\s*time_to_target:\s*\S", example, re.M))
check("the example names no action, service or write", not re.search(r"\b(tap_action|hold_action|service|action):", example))

# ===========================================================================
print("")
print("[5] routing is isolated data")
# ===========================================================================
routing = sources.get("scene/routing-v4.ts", "")
check("src/scene/routing-v4.ts imports nothing from the telemetry, motion or Lit layers and exports only data, types and the merge",
      routing != "" and not re.search(r"from \"(\.\./core|lit)", routing) and re.findall(r"^export function (\w+)", routing, re.M) == ["mergeRouting"]
      and "hass" not in routing and "callService" not in routing)
check("the renderer and the card read the routing through iso.ts (v4Layout), never the telemetry through routing-v4.ts",
      "routing-v4" in sources.get("scene/iso.ts", "") and "routing-v4" in sources.get("config.ts", "")
      and "routing-v4" not in sources.get("core/power.ts", "") and "routing-v4" not in sources.get("core/status.ts", ""))

# ===========================================================================
print("")
print("[6] the site renderer")
# ===========================================================================
rs = R.render_set(ROOT)
check("the site renderer renders the bundle and the example (and not the sources, tests or preview)",
      {f"frontend/{TAG}/dist/{TAG}.js", f"frontend/{TAG}/examples/ecco-example.yaml"} <= set(rs)
      and not [r for r in rs if r.startswith(f"frontend/{TAG}/") and "/dist/" not in r and "/examples/" not in r])
actions = R.firmware_actions(ROOT)
for p in (DIST, EXAMPLE):
    rel = p.relative_to(ROOT).as_posix()
    text = p.read_text(encoding="utf-8")
    ident, _c0 = R.render_text(rel, text, R.Site(), actions)
    custom, _c1 = R.render_text(rel, text, R.Site(device_slug="site_b_dongle"), actions)
    check(f"{rel}: the default site renders the identity; a custom slug replaces every default-slug entity id",
          ident == text and ("ecco_clock_dongle_" not in custom or p == DIST))

# ===========================================================================
print("")
print("[7] the card's Node suite")
# ===========================================================================
node = shutil.which("node")
ok_node = False
if node:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        major, minor = (int(x) for x in out.lstrip("v").split(".")[:2])
        ok_node = (major, minor) >= (22, 18)
    except Exception:  # noqa: BLE001
        out = "?"
if not ok_node:
    print(f"  SKIP  node --test (needs Node 22.18+ for TypeScript tests; found {out if node else 'no node'}) - run `npm test` in the card folder")
else:
    tests = sorted(str(p) for p in (CARD / "test").glob("*.test.ts"))
    r = subprocess.run([node, "--test", "--test-reporter=tap", *tests], cwd=str(CARD), capture_output=True, text=True, encoding="utf-8", timeout=900)
    counts = {k: int(v) for k, v in re.findall(r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", r.stdout, re.M)}
    tail = "\n".join(r.stdout.splitlines()[-12:]) + ("\n" + r.stderr[-800:] if r.returncode else "")
    check("node --test reports a complete TAP summary", {"tests", "pass", "fail", "cancelled", "skipped", "todo"} <= set(counts), tail)
    check(f"node --test: {counts.get('pass', '?')} passed, {counts.get('fail', '?')} failed, {counts.get('skipped', '?')} skipped of "
          f"{counts.get('tests', '?')} card tests; none failed, cancelled or todo; at least 70 passed",
          r.returncode == 0 and counts.get("fail") == 0 and counts.get("cancelled") == 0 and counts.get("todo") == 0
          and counts.get("pass", 0) >= 70 and counts.get("pass", 0) + counts.get("skipped", -1) == counts.get("tests"), tail)
    have_esbuild = (CARD / "node_modules" / "esbuild").is_dir()
    have_lit = (CARD / "node_modules" / "lit").is_dir()
    skips = re.findall(r"^\s*ok \d+ - (.+?) # SKIP (.*)$", r.stdout, re.M)
    rebuild = ["dist/ecco-flow-3d-card.js is the build of the current sources", "two builds of the same sources are byte-identical"]
    rendering = ["a link breathes exactly while its flow moves, and a card border exactly while one of its own links does",
                 "links default to the pulse style; particles and off render as before",
                 "still mode marks the scene still; one array draws one solar link; the vector scene has no links"]
    reason = {**{n: "esbuild is not installed" for n in rebuild}, **{n: "lit is not installed" for n in rendering}}
    allowed = sorted(([] if have_esbuild else rebuild) + ([] if have_lit else rendering))
    check(f"skipped tests are exactly the allowed ones ({'none' if not allowed else len(allowed)}: esbuild "
          f"{'installed' if have_esbuild else 'not installed'}, Lit {'installed' if have_lit else 'not installed'})",
          sorted(n for n, _why in skips) == allowed and counts.get("skipped") == len(allowed)
          and all(reason.get(n, "\0") in why for n, why in skips), str(skips))

# ===========================================================================
print("")
print("[8] scope and integration (ovw3): the Overview of the production dashboard, nowhere else")
# ===========================================================================
places =["deployment/ha-manifest.yaml", "VERSION.yaml", "home-assistant/dashboards/ecco_full_capability.yaml",
          *sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "home-assistant" / "packages").glob("*.yaml"))]
found = [rel for rel in places if (ROOT / rel).is_file() and TAG in (ROOT / rel).read_text(encoding="utf-8", errors="replace")]
check("the card is in no manifest (its bundle and resource are the preview's, copied by hand), package, version-file line or other "
      "dashboard", not found, str(found))
uses =[(v.get("title"), i, s, c) for v in dash.get("views", []) for i, s in enumerate(v.get("sections", []) or [])
        for c in (s.get("cards", []) or []) if isinstance(c, dict) and c.get("type") == f"custom:{TAG}"]
title, sec_i, sec, card = uses[0] if len(uses) == 1 else (None, None, {}, {})
check("the production dashboard uses the card exactly once: the one card of Overview section S3 (column span 3), in place of the 2D "
      "Energy Flow card, which the dashboard no longer uses",
      len(uses) == 1 and dash_text.count(f"type: custom:{TAG}") == 1 and title == "Overview" and sec_i == 2 and sec.get("type") == "grid"
      and sec.get("column_span") == 3 and sec.get("cards") == [card] and "custom:ecco-energy-flow-card" not in dash_text
      and "# ================= S3 ENERGY FLOW (span 3) =================\n" in dash_text, str([(t, i) for t, i, _s, _c in uses]))
ex_cfg = yaml.safe_load(example)
check("its configuration is the card's example (the ECCO 3D Preview's configuration, generic entity naming) plus the dashboard's grid "
      "layout only (no card_mod: the card styles its own ha-card); no action, service or routing override",
      {k: v for k, v in card.items() if k != "grid_options"} == ex_cfg and set(card) - set(ex_cfg) == {"grid_options"}
      and card.get("grid_options") == {"columns": "full", "rows": "auto"} and "card_mod" not in card
      and not re.search(r"\b(tap_action|hold_action|double_tap_action|service|action|perform_action):", yaml.safe_dump(card))
      and "routing" not in (card.get("scene") or {}) and "force" not in (card.get("scene") or {}) and not (card.get("scene") or {}).get("debug_anchors"))
check("dashboard 7.23.0 carries it, STAGED: the header note and VERSION.yaml at 7.23.0 or later with the 7.23.0 note, tested_in_home_assistant "
      "false", "# v7.23.0 (OVW3" in dash_text.split("views:")[0] and "# v7.23.0 (OVW3)" in (ROOT / "VERSION.yaml").read_text(encoding="utf-8")
      and tuple(int(x) for x in str(yaml.safe_load((ROOT / "VERSION.yaml").read_text(encoding="utf-8"))["current"]["dashboard"]["version"]).split(".")) >= (7, 23, 0)
      and yaml.safe_load((ROOT / "VERSION.yaml").read_text(encoding="utf-8"))["current"]["dashboard"].get("tested_in_home_assistant") is False)
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _scope_chain as _sc  # noqa: E402

_e = _sc.CHAIN.entry("ovw3")
_ids = [e.id for e in _sc.POST_EXPORT_ENTRIES]
check("the ovw3 entry is a post-export entry after acs1x (its order, not its position: a later entry may follow); it declares the dashboard "
      "and VERSION.yaml as its only frozen edits, no chain-pinned edit (no manifest stanza), its scope module as its one added file, and "
      "nothing else",
      "ovw3" in _ids and "acs1x" in _ids and _ids.index("ovw3") > _ids.index("acs1x") and not _e.reverts and not _e.checkpoints
      and set(_e.frozen_reverts) == set(_e.frozen_checkpoints) == {DASH_REL, "VERSION.yaml"}
      and _e.added_files == frozenset({"registry/tests/_ovw3_scope.py"}) and (ROOT / "registry" / "tests" / "_ovw3_scope.py").is_file()
      and not _e.deltas and not _e.banned_files and not _e.op_paths_changed and len(_e.fingerprint) == 64)
chain_mods = sorted(p.name for p in (ROOT / "registry" / "tests").glob("_*.py"))
named = [m for m in chain_mods if TAG in (ROOT / "registry" / "tests" / m).read_text(encoding="utf-8")]
check("exactly the ovw3 scope module and the chain (its entry) name the card among the scope / chain modules",
      len(chain_mods) > 10 and named == ["_ovw3_scope.py", "_scope_chain.py"], str(named))
install = raw["INSTALL_PREVIEW.md"].decode()
check("INSTALL_PREVIEW.md targets the preview dashboard, names the rollback and records the production placement (ovw3)",
      "PREVIEW" in install and "Rollback" in install and "ecco_pro" in install and "ovw3" in install)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All ECCO 3D Energy Flow card checks passed.")
print("These prove the card folder's shape, its read-only allowlist, its repository-sourced entity ids, its isolated routing data and "
      "its scope; the card's behaviour is proven by its own Node suite. They prove nothing about a live installation.")
