#!/usr/bin/env python3
"""Static boundaries that make the authority split hard to cross by accident:

  * ecco_core has no I/O beyond reading files: no network, serial, process, async or dynamic-execution imports or calls,
    no file writes, and no callable named like an actuation (there is no host-side write transport);
  * intelligence (every module, at any depth, tests aside) imports from ecco_core only the plain data model
    `ecco_core.state`, never capability, authority or bridge;
  * ecco_core.bridge never imports ecco_core.authority, and nothing in ecco_core imports the bridge;
  * the existing Intelligence authority-separation rules (tests/test_intelligence_arithmetic.py), applied RECURSIVELY to
    every intelligence module, so a future subpackage cannot slip outside them.
AST-based, offline."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def modules(pkg: str) -> list[Path]:
    return sorted(p for p in (ROOT / pkg).rglob("*.py") if "tests" not in p.relative_to(ROOT / pkg).parts)


def imports(tree: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.append(n.module)
        elif isinstance(n, ast.ImportFrom) and n.level > 0:
            out.append("." * n.level + (n.module or ""))
    return out


BAD_IMPORTS = {"socket", "requests", "urllib", "http", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus",
               "paho", "ssl", "ctypes", "importlib", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc", "subprocess",
               "os", "pty", "shutil", "signal", "threading", "sqlite3"}
BAD_CALLS = {"system", "popen", "Popen", "exec", "eval", "__import__", "execv", "spawn", "compile", "write_text", "write_bytes"}
ACTUATION = ("write", "send", "press", "arm", "apply", "execute", "actuate", "trigger", "set_register", "command")

print("[1] ecco_core: no I/O, no actuation")
core = modules("ecco_core")
check("ecco_core has modules to check", len(core) >= 6, str([p.name for p in core]))
viol = []
for p in core:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for m in imports(tree):
        if m.split(".")[0] in BAD_IMPORTS:
            viol.append((p.name, "import", m))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in BAD_CALLS:
                viol.append((p.name, "call", name))
            if name == "open":
                mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
                if mode is not None and not (isinstance(mode, ast.Constant) and set(str(mode.value)) <= {"r", "b", "t"}):
                    viol.append((p.name, "open", ast.unparse(mode)))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(n.name.lower().startswith(v) for v in ACTUATION):
            viol.append((p.name, "def", n.name))
        if isinstance(n, ast.AsyncFunctionDef):
            viol.append((p.name, "async def", n.name))
check("no network/serial/process/async/dynamic-exec import or call, no file write, no actuation-named callable", not viol, str(viol))

print("[2] the direction of every crossing")
intel = modules("intelligence")
bad_cross = []
for p in intel:
    for m in imports(ast.parse(p.read_text(encoding="utf-8"))):
        if m.split(".")[0] == "ecco_core" and m != "ecco_core.state":
            bad_cross.append((str(p.relative_to(ROOT)), m))
check("intelligence imports nothing from ecco_core but the plain data model ecco_core.state", not bad_cross, str(bad_cross))
check("intelligence.inputs is the module that reads the state model",
      "ecco_core.state" in imports(ast.parse((ROOT / "intelligence" / "inputs.py").read_text(encoding="utf-8"))))
bridge_imports = imports(ast.parse((ROOT / "ecco_core" / "bridge.py").read_text(encoding="utf-8")))
check("ecco_core.bridge never imports the authority layer", not [m for m in bridge_imports if "authority" in m], str(bridge_imports))
others = [(p.name, m) for p in core if p.name != "bridge.py"
          for m in imports(ast.parse(p.read_text(encoding="utf-8"))) if "bridge" in m or m.split(".")[0] == "intelligence"]
check("no other ecco_core module imports the bridge or Intelligence", not others, str(others))

print("[3] the Intelligence authority-separation rules, applied recursively")
I_BAD = {"socket", "requests", "urllib", "http", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus", "paho",
         "ssl", "ctypes", "importlib", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc"}
I_NO_PROCESS = {"subprocess", "os", "pty", "shutil"}
VOCAB = ("write_register", "modbus", "esphome.", "supervisor_token", "api/services", "call_service", "mqtt.publish")
iv = []
for p in intel:
    rel = p.relative_to(ROOT / "intelligence")
    in_tools = rel.parts[0] == "tools"
    allowed = {"preview_dashboard.py": {"subprocess"}}.get(p.name, set()) if in_tools else set()
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for m in imports(tree):
        top = m.split(".")[0]
        if top in I_BAD or (top in I_NO_PROCESS and top not in allowed and not (in_tools and top in {"os", "shutil"})):
            iv.append((str(rel), "import", m))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 200:
            if any(v in n.value.lower() for v in VOCAB):
                iv.append((str(rel), "vocab", n.value[:40]))
check(f"no forbidden import or control vocabulary in any of the {len(intel)} intelligence modules (any depth)", not iv, str(iv[:5]))
v11 = ("explain.py", "overnight.py", "charge_target.py", "events.py", "dump_advice.py", "inputs.py")
check("the V1.1 modules are top-level modules, so the original (non-recursive) scans cover them too",
      all((ROOT / "intelligence" / m).is_file() for m in v11))

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in ecco_core boundaries:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll ecco_core boundary checks passed")
