#!/usr/bin/env python3
"""Regression suite: the ECCO Weather & Solar card (frontend/ecco-weather-solar-card, read-only, not yet deployed).

  [1] the card folder: the expected files only, package / lock / hacs metadata, exact build-tool pins, text files only, LF
  [2] read-only allowlist over the source and the committed bundle: exactly two websocket message types
      (weather/subscribe_forecast, recorder/statistics_during_period), sent only from src/reader.ts; no service / action call,
      event subscription, network, storage, timer or dynamic code; one local view action
  [3] no reserved fallback / shadow token in any card file
  [4] the card's default entity ids are the ones this repository defines (the ECCO blend, scorecard and canonical PV template
      sensors, the controller's PV energy counters); the blend is read, never re-weighted
  [5] the bundle and the example render correctly for any site slug (tools/ecco_site_render.py)
  [6] the card's Node suite (node --test), when the host Node can run TypeScript tests (22.18+); otherwise reported as skipped
  [7] scope: one dashboard view right after Overview, declared by post-export entry wsc1; no manifest, package or version file

The card's behaviour (forecast lifecycle, freshness, time zones, sun times, chart, fallbacks) is tested by its Node suite:
frontend/ecco-weather-solar-card/test (npm test).

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
import yaml  # noqa: E402

CARD = ROOT / "frontend" / "ecco-weather-solar-card"
TAG = "ecco-weather-solar-card"
DIST = CARD / "dist" / f"{TAG}.js"
EXAMPLE = CARD / "examples" / "weather-solar-example.yaml"
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


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


# ===========================================================================
print("[1] the card folder")
# ===========================================================================
EXPECTED = {
    ".gitignore", "README.md", "build.mjs", "hacs.json", "package-lock.json", "package.json", "tsconfig.json",
    f"dist/{TAG}.js", "examples/weather-solar-example.yaml",
    "src/ecco-weather-solar-card.ts", "src/model.ts", "src/reader.ts", "src/render.ts", "src/styles.ts", "src/types.ts",
    "test/build.test.ts", "test/card.test.ts", "test/dom-shim.ts", "test/fixtures.ts", "test/model.test.ts", "test/render.test.ts",
    "test/static.test.ts",
}
files = card_files()
check("the card folder holds exactly the expected files (sources, tests, dist, example, metadata)", set(files) == EXPECTED,
      f"extra {sorted(set(files) - EXPECTED)} missing {sorted(EXPECTED - set(files))}")
binary = [f for f in files if b"\0" in (CARD / f).read_bytes()]
crlf = [f for f in files if b"\r\n" in (CARD / f).read_bytes()]
check("text files only (no binary), LF line endings", not binary and not crlf, f"{binary} {crlf}")
pkg = json.loads((CARD / "package.json").read_text(encoding="utf-8"))
lock = json.loads((CARD / "package-lock.json").read_text(encoding="utf-8"))
check("package.json: private, module, GPL-3.0-or-later, no runtime dependency, esbuild 0.28.1 / typescript 5.9.3 exactly",
      pkg.get("name") == TAG and pkg.get("private") is True and pkg.get("type") == "module" and pkg.get("license") == "GPL-3.0-or-later"
      and "dependencies" not in pkg and pkg.get("devDependencies") == {"esbuild": "0.28.1", "typescript": "5.9.3"})
check("package-lock.json v3 agrees (root name, licence, pins)",
      lock.get("lockfileVersion") == 3 and lock.get("name") == TAG and lock["packages"][""].get("name") == TAG
      and lock["packages"][""].get("license") == "GPL-3.0-or-later" and lock["packages"][""].get("devDependencies") == pkg["devDependencies"]
      and lock["packages"]["node_modules/esbuild"]["version"] == "0.28.1" and lock["packages"]["node_modules/typescript"]["version"] == "5.9.3")
hacs = json.loads((CARD / "hacs.json").read_text(encoding="utf-8"))
check("hacs.json names the built file", hacs.get("filename") == f"{TAG}.js" and hacs.get("content_in_root") is False)
check(".gitignore keeps node_modules out", "node_modules/" in (CARD / ".gitignore").read_text(encoding="utf-8").split())

# ===========================================================================
print("")
print("[2] read-only allowlist (source and bundle)")
# ===========================================================================
ALLOWED = ["recorder/statistics_during_period", "weather/subscribe_forecast"]
FORBIDDEN = ["callService", "callWS", "callApi", "fetchWithAuth", "subscribeEvents", "perform_action", "return_response",
             "call_service", "execute_script", "fire_event", "subscribe_events", "subscribe_trigger", "render_template",
             "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "localStorage", "sessionStorage", "indexedDB", "postMessage",
             "document.cookie", "hass-action", "hass-more-info", "dispatchEvent", "button.press", "switch.turn_", "number.set_value",
             "select.select_option", "modbus", "esphome."]
FORBIDDEN_RE = [r"\bfetch\s*\(", r"\beval\s*\(", r"\bnew\s+Function\s*\(", r"\bimport\s*\(", r"\bset(?:Interval|Timeout)\s*\(",
                r"\brequestAnimationFrame\s*\(", r"\bsendMessage\b(?!Promise)"]
WS = re.compile(r"[\"'`](?:auth|config|lovelace|energy|history|logbook|recorder|weather|frontend|search|repairs|backup|person|template|"
                r"automation|script|system_log|hassio|supervisor)/[a-z_/]+[\"'`]")
sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(SRC.glob("*.ts"))}
dist = DIST.read_text(encoding="utf-8")
for name, text in sources.items():
    bad = [t for t in FORBIDDEN if t in text] + [r for r in FORBIDDEN_RE if re.search(r, text)]
    check(f"src/{name}: no service, action, event, network, storage, timer or dynamic-code API", not bad, str(bad))
    code = code_only(text)
    touches = bool(re.search(r"\bsubscribeMessage\b|\bsendMessagePromise\b", code))
    types = sorted({m.group(0)[1:-1] for m in WS.finditer(code)})
    check(f"src/{name}: {'the only module that touches the connection; it names exactly the two allowed messages' if name == 'reader.ts' else 'never touches the connection'}",
          touches == (name == "reader.ts") and types == (ALLOWED if name == "reader.ts" else []), f"{touches} {types}")
reader = code_only(sources.get("reader.ts", ""))
check("src/reader.ts sends one subscription and one query, and builds exactly two message objects",
      reader.count("conn.subscribeMessage(") == 1 and reader.count("conn.sendMessagePromise(") == 1 and len(re.findall(r"\btype:", reader)) == 2)
card_src = code_only(sources.get(f"{TAG}.ts", ""))
check("the element reads only states / config / connection from hass and never assigns hass or its connection to itself",
      sorted(set(re.findall(r"\bh\.([A-Za-z_]+)", card_src))) == ["config", "connection", "states"]
      and not re.search(r"this\.(?:_?hass|_?connection|_?conn)\s*=", card_src) and card_src.count("set hass(") == 1)
alls = "\n".join(code_only(t) for t in sources.values())
check("one listener (click) and one local view action (chart-day)",
      re.findall(r"addEventListener\(\s*\"([a-z]+)\"", alls) == ["click"]
      and sorted(set(re.findall(r"data-action=\"([a-z-]+)\"", alls))) == ["chart-day"])
bad = [t for t in FORBIDDEN if t in dist] + [r for r in FORBIDDEN_RE if re.search(r, dist)]
check("the bundle names no forbidden API", not bad, str(bad))
check("the bundle contains exactly the two allowed message types", sorted({m.group(0)[1:-1] for m in WS.finditer(dist)}) == ALLOWED)
check("the bundle is self-contained: no import, no require, no source map, no local path",
      not re.search(r"(?:^|[;\n])\s*import\s*[\s{*\"']", dist) and "require(" not in dist and "sourceMappingURL" not in dist
      and not re.search(r"[A-Za-z]:\\|/Users/|/home/|node_modules", dist))

# ===========================================================================
print("")
print("[3] reserved tokens")
# ===========================================================================
# Assembled from fragments so this file never spells the reserved tokens itself (the repository-wide scope scans would trip).
FB, FL = "fail" + "back", "fall" + "back"
RESERVED = re.compile("|".join([f"ecco_{FL}", f"{FL.upper()}_PROFILE", f"{FB.upper()}_STATE", f"ecco_{FB}", "ecco_" + "shadow_",
                                "Shadow " + "Recovery", f"{FB}_shadow", "fbc" + "_raw_", f"{FL}_profile_live" + "_match"]))
hits = [f for f in files if RESERVED.search((CARD / f).read_text(encoding="utf-8"))]
check("no card file spells a reserved fallback / shadow token", not hits, str(hits))

# ===========================================================================
print("")
print("[4] default entities are the repository's own")
# ===========================================================================
model = sources.get("model.ts", "")
defaults = dict(re.findall(r"^\s{2}([a-z_]+): \"([a-z_]+\.[a-z0-9_]+)\",$", model[model.index("DEFAULT_ENTITIES"):model.index("DEFAULT_STALE")], re.M))


def template_sensor_ids(rel: str) -> set[str]:
    doc = yaml.load((ROOT / rel).read_text(encoding="utf-8"), Loader=Loader) or {}
    out = set()
    for block in doc.get("template", []) or []:
        for plat in ("sensor", "binary_sensor"):
            for ent in block.get(plat, []) or []:
                if isinstance(ent, dict) and isinstance(ent.get("name"), str):
                    out.add(f"{plat}.{re.sub(r'_+', '_', re.sub(r'[^a-z0-9]', '_', ent['name'].lower())).strip('_')}")
    return out


ha_ids = template_sensor_ids("home-assistant/packages/ecco_pro.yaml") | template_sensor_ids("home-assistant/packages/ecco_canonical_telemetry.yaml")
ecco_keys = ["blend_today", "blend_remaining", "blend_tomorrow", "blend_mae", "solcast_mae", "forecast_solar_mae", "blend_error",
             "solcast_error", "forecast_solar_error", "best_source", "learning_days", "pv_power"]
missing = [f"{k}={defaults.get(k)}" for k in ecco_keys if defaults.get(k) not in ha_ids]
check(f"the {len(ecco_keys)} ECCO template-sensor defaults are defined by the repository's HA packages", not missing and len(defaults) == 25, str(missing))
fw = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")
check("the PV energy defaults are the controller's 'ECCO Day PV Energy' / 'ECCO Total PV Energy' (total_increasing kWh) sensors",
      defaults.get("pv_today") == "sensor.ecco_clock_dongle_ecco_day_pv_energy" and defaults.get("pv_energy_statistic") == "sensor.ecco_clock_dongle_ecco_total_pv_energy"
      and 'name: "ECCO Day PV Energy"' in fw and 'name: "ECCO Total PV Energy"' in fw)
pro = (ROOT / "home-assistant" / "packages" / "ecco_pro.yaml").read_text(encoding="utf-8")
provider = ["solcast_today", "solcast_tomorrow", "solcast_remaining", "forecast_solar_today", "forecast_solar_remaining", "forecast_solar_tomorrow"]
check("the provider defaults are the ids the ECCO blend itself reads", all(defaults.get(k, "@") in pro for k in provider),
      str([k for k in provider if defaults.get(k, "@") not in pro]))
check("the ECCO blend stays the 50/50 mean defined in the package (the card reads it and declares no weighting of its own)",
      "50/50 mean when both sources valid; single-source fallback" in pro and not re.search(r"weight", code_only(model), re.I))

# ===========================================================================
print("")
print("[5] the site renderer")
# ===========================================================================
rs = R.render_set(ROOT)
check("the site renderer renders the bundle and the example (and not the sources or tests)",
      {f"frontend/{TAG}/dist/{TAG}.js", f"frontend/{TAG}/examples/weather-solar-example.yaml"} <= set(rs)
      and not [r for r in rs if r.startswith(f"frontend/{TAG}/") and "/dist/" not in r and "/examples/" not in r])
actions = R.firmware_actions(ROOT)
for p in (DIST, EXAMPLE):
    rel = p.relative_to(ROOT).as_posix()
    text = p.read_text(encoding="utf-8")
    ident, _c0 = R.render_text(rel, text, R.Site(), actions)
    custom, _c1 = R.render_text(rel, text, R.Site(device_slug="site_b_dongle"), actions)
    check(f"{rel}: the default site renders the identity; a custom slug replaces every default-slug entity id",
          ident == text and "site_b_dongle_ecco_total_pv_energy" in custom and "ecco_clock_dongle_ecco_total_pv_energy" not in custom)

# ===========================================================================
print("")
print("[6] the card's Node suite")
# ===========================================================================
node = shutil.which("node")
ver = None
if node:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        m = re.match(r"v(\d+)\.(\d+)", out)
        ver = (int(m.group(1)), int(m.group(2))) if m else None
    except (OSError, subprocess.SubprocessError):
        ver = None
if ver is None or ver < (22, 18):
    print(f"  SKIP  node --test (needs Node 22.18+ for TypeScript tests; found {ver}) - run `npm test` in the card folder")
else:
    tests = sorted(str(p.relative_to(CARD)) for p in (CARD / "test").glob("*.test.ts"))
    r = subprocess.run([node, "--test", *tests], cwd=str(CARD), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    summary = dict(re.findall(r"^ℹ (tests|pass|fail) (\d+)$", r.stdout, re.M))
    check(f"node --test: {summary.get('pass', '?')}/{summary.get('tests', '?')} card tests pass (at least 80)",
          r.returncode == 0 and summary.get("fail") == "0" and int(summary.get("pass", "0")) >= 80, (r.stdout + r.stderr)[-800:])

# ===========================================================================
print("")
print("[7] scope: one dashboard view right after Overview (post-export entry wsc1); no manifest, package or version file")
# ===========================================================================
dash_rel = "home-assistant/dashboards/ecco_pro.yaml"
places = ["deployment/ha-manifest.yaml", "VERSION.yaml",
          *sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "home-assistant" / "packages").glob("*.yaml"))]
found = [rel for rel in places if (ROOT / rel).is_file() and TAG in (ROOT / rel).read_text(encoding="utf-8")]
check("the card is in no manifest, package or version file (deployed as a manual Lovelace resource, like the flow card)", not found, str(found))
dash = yaml.load((ROOT / dash_rel).read_text(encoding="utf-8"), Loader=Loader) or {}
views = dash.get("views") or []
titles = [v.get("title") for v in views if isinstance(v, dict)]
uses = [i for i, v in enumerate(views) if isinstance(v, dict) and f"custom:{TAG}" in yaml.dump(v)]
check("the dashboard has exactly one Weather & Solar view, immediately after Overview, and the card appears in no other view",
      titles[:2] == ["Overview", "Weather & Solar"] and uses == [1], f"{titles[:3]} {uses}")
wv = views[1] if len(views) > 1 and isinstance(views[1], dict) else {}
cards = [c for s in (wv.get("sections") or []) for c in (s.get("cards") or [])]
check("the view holds only the card, with its default entities (no entity id typed into the dashboard)",
      wv.get("path") == "ecco-weather-solar" and wv.get("type") == "sections" and cards == [{"type": f"custom:{TAG}", "grid_options": {"columns": "full"}}],
      str(cards))
chain_mods = sorted((ROOT / "registry" / "tests").glob("_*.py"))
named = [p.name for p in chain_mods if re.search(r"ecco-weather-solar-card|weather_solar", p.read_text(encoding="utf-8"))]
check("only the dashboard entry names the card: its scope module _wsc1_scope.py and its chain entry in _scope_chain.py",
      named == ["_scope_chain.py", "_wsc1_scope.py"], str(named))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All Weather & Solar card checks passed.")
