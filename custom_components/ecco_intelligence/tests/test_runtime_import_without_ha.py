#!/usr/bin/env python3
"""Every runtime/*.py module and the package __init__ import with homeassistant ABSENT (L1).

In a fresh interpreter (-I), `sys.modules['homeassistant'] = None` makes any homeassistant import raise ImportError; then the
package, const and every runtime module are imported:
  * from the SOURCE tree (the repository root on sys.path), and
  * from the BUILT kit (only the build directory on sys.path): there the engine comes from the package's own _vendor copy,
    and no top-level `intelligence` or `ecco_core` module is ever imported (nothing on Home Assistant's global path).
The HA-coupled modules (coordinator, sensor, binary_sensor, config_flow, diagnostics, entity_base) are expected to need
homeassistant, and do. Plain script; exits 1 on any failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[2]
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


PREFIX = "ecco_intel_import_"
RUNTIME = sorted(p.stem for p in (TESTS.parent / "runtime").glob("*.py") if p.stem != "__init__")
HA_COUPLED = ("coordinator", "sensor", "binary_sensor", "config_flow", "diagnostics", "entity_base")
CHILD = r'''
import importlib, json, sys
sys.modules["homeassistant"] = None          # any homeassistant import now raises ImportError
sys.path.insert(0, sys.argv[1])
ok, errors, needs_ha = [], {}, {}
names = ["custom_components.ecco_intelligence", "custom_components.ecco_intelligence.const",
         "custom_components.ecco_intelligence.runtime"] + ["custom_components.ecco_intelligence.runtime." + m for m in json.loads(sys.argv[2])]
for n in names:
    try:
        importlib.import_module(n); ok.append(n)
    except Exception as exc:
        errors[n] = f"{type(exc).__name__}: {exc}"
for m in json.loads(sys.argv[3]):
    try:
        importlib.import_module("custom_components.ecco_intelligence." + m); needs_ha[m] = "imported"
    except ImportError as exc:
        needs_ha[m] = "needs homeassistant" if "homeassistant" in str(exc) else f"ImportError: {exc}"
top = sorted(k for k in sys.modules if k.split(".")[0] in ("intelligence", "ecco_core"))
ha = sorted(k for k, v in sys.modules.items() if k.split(".")[0] == "homeassistant" and v is not None)
integ = importlib.import_module("custom_components.ecco_intelligence")
print(json.dumps({"ok": ok, "errors": errors, "needs_ha": needs_ha, "top_level_engine": top, "ha_loaded": ha,
                  "platforms": list(integ.PLATFORMS), "mode": integ.MODE,
                  "setup_is_coroutine": __import__("inspect").iscoroutinefunction(integ.async_setup_entry)}))
'''


def child(path: Path) -> dict:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, str(path), json.dumps(RUNTIME), json.dumps(HA_COUPLED)],
                       capture_output=True, text=True, timeout=300, cwd=str(path), env=env)
    if p.returncode != 0 or not p.stdout.strip():
        return {"crash": (p.stdout + p.stderr)[-600:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


check("the runtime package has its six modules", RUNTIME == ["engine_link", "gates", "history_source", "selftest", "sources",
                                                             "store"], str(RUNTIME))
print("== the source tree, homeassistant absent")
r = child(REPO)
check("no crash", "crash" not in r, r.get("crash", ""))
check(f"the package, const and all {len(RUNTIME)} runtime modules import", not r.get("errors") and len(r.get("ok", [])) == 3 + len(RUNTIME),
      str(r.get("errors")))
check("no homeassistant module was loaded", r.get("ha_loaded") == [], str(r.get("ha_loaded")))
check("the HA-coupled modules do need homeassistant (lazy everywhere else)",
      all(v == "needs homeassistant" for v in r.get("needs_ha", {}).values()) and len(r.get("needs_ha", {})) == len(HA_COUPLED),
      str(r.get("needs_ha")))
check("the package exposes SHADOW, the two platforms and an async setup", r.get("mode") == "SHADOW"
      and r.get("platforms") == ["sensor", "binary_sensor"] and r.get("setup_is_coroutine") is True)

root = H.mktemp(PREFIX)
try:
    kit = root / "kit"
    b = H.build_kit(kit)
    check("the kit builds", b.returncode == 0, b.stderr[-300:])
    print("== the built kit, homeassistant absent, only the build directory on sys.path")
    k = child(kit)
    check("no crash", "crash" not in k, k.get("crash", ""))
    check(f"the package, const and all {len(RUNTIME)} runtime modules import from the kit",
          not k.get("errors") and len(k.get("ok", [])) == 3 + len(RUNTIME), str(k.get("errors")))
    check("no top-level intelligence / ecco_core module is imported (the engine is the package's _vendor copy)",
          k.get("top_level_engine") == [], str(k.get("top_level_engine")))
    check("no homeassistant module was loaded", k.get("ha_loaded") == [])
    check("the HA-coupled modules need homeassistant in the kit too",
          all(v == "needs homeassistant" for v in k.get("needs_ha", {}).values()), str(k.get("needs_ha")))
finally:
    H.rmtree_own(root, PREFIX)


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime import without homeassistant:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime import without homeassistant checks passed")
