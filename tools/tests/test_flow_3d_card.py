#!/usr/bin/env python3
"""Regression suite: the ECCO 3D Energy Flow card (frontend/ecco-flow-3d-card, read-only; not yet installed anywhere).

  [1] the card folder: the expected files only, package / lock / hacs metadata, text files only, LF
  [2] read-only allowlist over the source and the committed bundle: no service / action / websocket / network / storage /
      dynamic-code API; the only dispatched event is Home Assistant's own hass-more-info; the two timers it does use are the
      15 s clock refresh and the particle animation frame; no fetch, no import() of anything
  [3] no reserved fallback / shadow token in any card file
  [4] the example's entity ids are the repository's own (packages, dashboard, canonical aliases, firmware sensor names); the
      sign conventions match the installed Energy Flow card's example
  [5] routing is isolated data: src/scene/routing-v4.ts imports nothing from the telemetry, motion or Lit layers
  [6] the site renderer renders the bundle and the example (and not the sources or tests)
  [7] the card's Node suite (node --test, TAP), when the host Node can run TypeScript tests (22.18+); otherwise reported as skipped
  [8] scope: the card is in no manifest, package, version file or dashboard (an offline prototype; preview install is a
      separate owner-authorised step, see INSTALL_PREVIEW.md)

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
from pathlib import Path

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
    "src/scene/icons.ts", "src/scene/iso.ts", "src/scene/routing-v4.ts", "src/scene/scene.ts",
    "test/artworkLayout.test.ts", "test/build.test.ts", "test/flow.test.ts", "test/geometry.test.ts", "test/motion.test.ts",
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
check("timers: the 15 s clock refresh, the crossfade settle timeout and the particle animation frame, nothing else",
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


def corpus_text() -> str:
    parts = []
    for d in ("home-assistant", "registry", "docs"):
        for p in (ROOT / d).rglob("*"):
            if p.is_file() and p.suffix in {".yaml", ".yml", ".md", ".json"}:
                parts.append(p.read_text(encoding="utf-8", errors="replace"))
    for p in (ROOT / "frontend").rglob("*"):
        if p.is_file() and p.suffix in {".yaml", ".ts", ".md"} and "node_modules" not in p.parts and not str(p).startswith(str(CARD)):
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


corpus = corpus_text()
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

# ===========================================================================
print("")
print("[8] scope: an offline prototype, installed nowhere")
# ===========================================================================
places = ["deployment/ha-manifest.yaml", "VERSION.yaml", "home-assistant/dashboards/ecco_pro.yaml", "home-assistant/dashboards/ecco_full_capability.yaml",
          *sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "home-assistant" / "packages").glob("*.yaml"))]
found = [rel for rel in places if (ROOT / rel).is_file() and TAG in (ROOT / rel).read_text(encoding="utf-8", errors="replace")]
check("the card is in no manifest, package, version file or dashboard (preview install is a separate owner-authorised step)", not found, str(found))
check("INSTALL_PREVIEW.md targets the preview dashboard and names the rollback",
      "PREVIEW" in raw["INSTALL_PREVIEW.md"].decode() and "Rollback" in raw["INSTALL_PREVIEW.md"].decode() and "ecco_pro" in raw["INSTALL_PREVIEW.md"].decode())

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All ECCO 3D Energy Flow card checks passed.")
print("These prove the card folder's shape, its read-only allowlist, its repository-sourced entity ids, its isolated routing data and "
      "its scope; the card's behaviour is proven by its own Node suite. They prove nothing about a live installation.")
