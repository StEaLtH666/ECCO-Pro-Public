#!/usr/bin/env python3
"""ECCO Intelligence SHADOW runtime (custom_components/ecco_intelligence): static read-only boundaries (AST-based).

Every .py file under custom_components/ecco_intelligence except the package's own top-level tests/ is scanned (a nested
"tests" package is production code and is scanned too; production code may not import a tests package). Each check is
vacuous while nothing is present and strict as soon as something is:

  [1] a POSITIVE Home Assistant import allowlist (anything else fails), restricted names for recorder / statistics /
      device_registry / helpers.event (async_track_time_interval, async_track_state_change_event, async_call_later: the
      one timer, the one state listener on the telemetry poll text and the poll-driven step of A23, each called from one
      place in coordinator.py; the only bus listener the one-shot homeassistant_started one); no module-level
      homeassistant import in __init__.py (any compound statement counts as module level; only functions and
      `if TYPE_CHECKING:` do not); none at all in runtime/*.py
  [2] a POSITIVE import allowlist for everything else: pure standard-library modules anywhere; asyncio only in
      __init__.py and coordinator.py; os / sqlite3 / pathlib / tempfile / io only in runtime/store.py; voluptuous (the
      config-flow schema library Home Assistant ships); the repository's intelligence / ecco_core / this package. Banned
      outright: network, process, serial, dynamic import, os back ends, serialisation-to-disk modules, ecco_autonomy,
      ecco_core.authority / capability, HA storage and RestoreEntity / RestoreSensor
  [3] banned names: service calls, state writes (also the sync hass.states.set / remove and hass.bus.fire), event fires,
      registry and statistics writes (also the async_register* / async_clear_* / async_adjust_* / async_import* /
      async_update_statistics* / async_change_statistics* families), storage, logging file / socket handlers; no
      __import__ / exec / eval / compile / vars / globals / locals / setattr / delattr; getattr / hasattr only with a
      constant, allowed attribute name; no dunder object access (__setattr__, __dict__, ...); no string constant equal to a
      banned name
  [4] banned strings (write and control vocabulary, ACS1 / Free Power / Dump / recovery script names)
  [5] platforms: only sensor and binary_sensor (as modules or packages); no services.yaml / services.py; no hacs.json
      under custom_components/; no compiled or path-hook file (.so / .pyd / .pth / .dll, or a .pyc outside __pycache__)
  [6] file writes (open for writing, write_text / write_bytes, sqlite3.connect, os.replace / rename / remove ...) only
      in runtime/store.py
  [7] manifest.json (when any source exists): requirements [], dependencies within ['recorder'], iot_class 'calculated',
      no 'services'
  [8] provenance can never be widened at run time: no source passes the keyword accept_provenance, passes it by position
      (positional limits on gate / satisfied / required_inputs / freshness_limits / apply_to_siteconfig /
      capacity_sources_context / provenance_ok / CycleInputs), expands * or ** into those calls or into replace(), names
      a provenance constant (SYNTHETIC_TEST, SYNTHETIC_EXAMPLE, CALLER_DECLARATION_UNVERIFIED, OWNER_RECORD, Provenance,
      ALL_PROVENANCE), or builds a decision in code (decide / with_decision / Decision / DecisionSet(...)); decisions are
      loaded only with DecisionSet.from_mapping(..., source='site_local')
  [9] when tools/build_ha_integration.py exists: build with the frozen command line into a temporary directory, apply the
      integration rules to the built non-_vendor files and the Intelligence rules to _vendor, and check the vendor
      closure, VENDOR_MANIFEST.json / SHA256SUMS, and that no _vendor/ path is tracked by git
Plain script: exits 1 on any failure. Offline. Tighten-only; not open to a contract change request.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "custom_components" / "ecco_intelligence"
CC = ROOT / "custom_components"
BUILD_TOOL = ROOT / "tools" / "build_ha_integration.py"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# ---------------------------------------------------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------------------------------------------------

HA_ALLOWED: dict[str, frozenset | None] = {      # None = any name from the module; a set = only these names
    "homeassistant.core": None,
    "homeassistant.const": None,
    "homeassistant.config_entries": None,
    "homeassistant.exceptions": None,
    "homeassistant.components.sensor": None,
    "homeassistant.components.binary_sensor": None,
    "homeassistant.components.diagnostics": None,
    "homeassistant.components.recorder": frozenset({"get_instance"}),
    "homeassistant.components.recorder.statistics": frozenset({"statistics_during_period", "list_statistic_ids"}),
    # the one timer, the one state listener (A23: the mapped telemetry poll text) and the poll-driven step's one-shot
    "homeassistant.helpers.event": frozenset({"async_track_time_interval", "async_track_state_change_event",
                                              "async_call_later"}),
    "homeassistant.helpers.device_registry": frozenset({"DeviceInfo", "DeviceEntryType"}),
    "homeassistant.helpers.entity_platform": None,
    "homeassistant.helpers.typing": None,
    "homeassistant.util.dt": None,
}
BANNED_NAMES = frozenset({
    "services", "async_call", "async_register", "async_set", "async_set_internal", "async_fire", "async_remove",
    "async_add_external_statistics", "async_import_statistics", "async_save", "async_delay_save", "async_update_entry",
    "async_create", "async_get_or_create", "async_update_device", "async_update_entity", "async_remove_device",
    "async_reload", "RestoreEntity", "RestoreSensor", "Store", "async_fire_internal", "async_update_statistics_metadata",
    "async_clear_statistics", "async_adjust_statistics", "async_change_statistics_unit", "async_register_entity_service",
    "async_register_admin_service", "async_set_options", "async_remove_entry",
})
# whole families of write names (prefix match on attribute names, called names and imported names)
BANNED_PREFIXES = ("async_register", "async_clear_", "async_adjust_", "async_update_statistics", "async_change_statistics",
                   "async_import", "async_add_external", "async_delete", "async_purge")
# the sync twins of the banned state / event writes, judged on their receiver (hass.states.set, hass.bus.fire, ...)
STATE_BUS_WRITES = frozenset({"set", "fire", "remove", "async_set", "async_fire", "async_remove", "async_set_internal",
                              "async_fire_internal", "async_remove_internal"})
LOG_FILE_HANDLERS = frozenset({"FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler", "WatchedFileHandler",
                               "SocketHandler", "DatagramHandler", "SysLogHandler", "HTTPHandler", "SMTPHandler",
                               "NTEventLogHandler", "QueueListener", "basicConfig", "fileConfig", "dictConfig"})
DUNDER_BANNED = frozenset({"__setattr__", "__delattr__", "__dict__", "__globals__", "__builtins__", "__code__",
                           "__subclasses__", "__import__", "__loader__", "__getattribute__", "__closure__"})
DYNAMIC_CALLS = frozenset({"__import__", "exec", "eval", "compile", "vars", "globals", "locals", "breakpoint", "setattr",
                           "delattr", "input"})
BANNED_IMPORTS = ("socket", "urllib", "http", "aiohttp", "requests", "ssl", "subprocess", "multiprocessing", "ctypes",
                  "importlib", "pty", "webbrowser", "paho", "pymodbus", "serial", "telnetlib", "xmlrpc", "ftplib", "smtplib",
                  "ecco_autonomy", "ecco_core.authority", "ecco_core.capability", "homeassistant.helpers.storage",
                  "homeassistant.helpers.restore_state", "nt", "posix", "_socket", "_thread", "_winapi", "msvcrt",
                  "builtins", "pickle", "shelve", "dbm", "marshal", "runpy", "socketserver", "selectors", "select", "mmap",
                  "signal", "threading", "concurrent", "logging.handlers", "logging.config", "sys", "code", "pdb")
# the positive allowlist for everything that is not homeassistant
RT_STDLIB_ANY = frozenset({"__future__", "abc", "bisect", "calendar", "collections", "contextlib", "copy", "dataclasses",
                           "datetime", "decimal", "enum", "fractions", "functools", "hashlib", "heapq", "itertools", "json",
                           "logging", "math", "numbers", "operator", "re", "statistics", "string", "textwrap", "time",
                           "traceback", "types", "typing", "warnings", "weakref", "zoneinfo"})
RT_DENIED_SUBMODULES = frozenset({"logging.handlers", "logging.config", "json.tool"})
RT_STORE_ONLY = frozenset({"os", "sqlite3", "pathlib", "tempfile", "io"})
RT_ASYNC_ONLY = frozenset({"asyncio"})
RT_ASYNC_FILES = ("__init__.py", "coordinator.py")
RT_THIRD_PARTY = frozenset({"voluptuous"})
RT_REPO = frozenset({"intelligence", "ecco_core", "custom_components"})
BANNED_STRINGS = ("write_register", "modbus", "esphome.", "supervisor_token", "api/services", "call_service", "mqtt.publish",
                  "ecco_cfg_apply", "ecco_cfg_review", "apply_manual_slot", "write_enable", "start_free_power",
                  "start_dump_to_grid", "input_text.ecco_cfg_edit_review", "recovery_execute", "fallback_profile_execute")
PROVENANCE_NAMES = frozenset({"SYNTHETIC_TEST", "SYNTHETIC_EXAMPLE", "CALLER_DECLARATION_UNVERIFIED", "OWNER_RECORD",
                              "Provenance", "ALL_PROVENANCE"})
# calls that take accept_provenance: at most this many positional arguments (fewer than its position), no * / **
ACCEPT_POSITIONAL_LIMIT = {"gate": 3, "apply_to_siteconfig": 3, "required_inputs": 2, "freshness_limits": 1, "satisfied": 1,
                           "capacity_sources_context": 2, "provenance_ok": 0, "CycleInputs": 9}
NO_STAR_CALLS = frozenset(ACCEPT_POSITIONAL_LIMIT) | {"replace", "assemble_envelope", "starting_envelope", "paused_envelope",
                                                     "self_test_failed_envelope", "stale_from", "with_last_good",
                                                     "from_mapping", "DecisionSet"}
DECISION_BUILDERS = frozenset({"decide", "_decide", "with_decision", "Decision", "_record_problems"})
HA_PLATFORMS = frozenset({
    "air_quality", "alarm_control_panel", "assist_satellite", "binary_sensor", "button", "calendar", "camera", "climate",
    "conversation", "cover", "date", "datetime", "device_tracker", "event", "fan", "geo_location", "humidifier", "image",
    "image_processing", "lawn_mower", "light", "lock", "media_player", "notify", "number", "remote", "scene", "select",
    "sensor", "siren", "stt", "switch", "text", "time", "todo", "tts", "update", "vacuum", "valve", "wake_word",
    "water_heater", "weather",
})
ALLOWED_PLATFORMS = frozenset({"sensor", "binary_sensor"})
# A23: each Home Assistant event helper is called from exactly one place, in coordinator.py (the one timer, the one state
# listener, the one place that schedules the poll-driven step), and bus listeners only for homeassistant_started
EVENT_HELPER_SITES = {"async_track_time_interval": 1, "async_track_state_change_event": 1, "async_call_later": 1}
EVENT_HELPER_FILE = "coordinator.py"
BUS_LISTEN_NAMES = frozenset({"async_listen", "async_listen_once", "listen", "listen_once"})
BINARY_SUFFIXES = (".so", ".pyd", ".pth", ".dll", ".dylib", ".exe")
WRITE_ATTRS = frozenset({"write_text", "write_bytes", "unlink", "rmdir", "mkdir", "makedirs", "touch", "rename", "removedirs",
                         "symlink_to", "hardlink_to", "chmod"})
OS_WRITES = frozenset({"replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs", "removedirs", "renames",
                       "truncate", "write", "open", "chmod", "link", "symlink", "system", "popen"})
# the Intelligence rules applied to the vendored copy (tests/test_intelligence_arithmetic.py, ecco_core boundaries)
I_BAD = frozenset({"socket", "requests", "urllib", "http", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus",
                   "paho", "ssl", "ctypes", "importlib", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc", "subprocess",
                   "os", "pty", "shutil", "signal", "threading", "sqlite3", "homeassistant", "ecco_autonomy", "nt", "posix",
                   "_socket", "_thread", "builtins", "pickle", "shelve", "marshal", "runpy", "tempfile"})
I_CALLS = frozenset({"system", "popen", "Popen", "exec", "eval", "__import__", "execv", "spawn", "compile"})
I_VOCAB = ("write_register", "modbus", "esphome.", "supervisor_token", "api/services", "call_service", "mqtt.publish")


def is_test_path(rel_parts: tuple[str, ...]) -> bool:
    """Only the package's own top-level tests/ directory is test code."""
    return bool(rel_parts) and rel_parts[0] == "tests"


def imported(tree: ast.AST) -> list[tuple[str, tuple[str, ...], int, ast.AST]]:
    """(absolute-or-relative module, imported names, level, node) for every import."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.append((a.name, (), 0, n))
        elif isinstance(n, ast.ImportFrom):
            out.append((n.module or "", tuple(a.name for a in n.names), n.level, n))
    return out


def module_level_nodes(tree: ast.Module) -> set[int]:
    """ids of import nodes that run at import time: everything except the bodies of functions / lambdas and of
    `if TYPE_CHECKING:` (its else branch does run). Every compound statement (if, for, while, with, try, match, class...)
    is recursed into."""
    ids: set[int] = set()

    def is_tc(test: ast.AST) -> bool:
        return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")

    def visit(stmts) -> None:
        for st in stmts:
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                ids.add(id(st))
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            elif isinstance(st, ast.If) and is_tc(st.test):
                visit(st.orelse)
            else:
                for _name, value in ast.iter_fields(st):
                    if isinstance(value, list):
                        for v in value:
                            if isinstance(v, ast.stmt):
                                visit([v])
                            elif isinstance(v, (ast.ExceptHandler, ast.match_case)):
                                visit(v.body)
    visit(tree.body)
    return ids


def ha_violations(mod: str, names: tuple[str, ...], level: int) -> list[str]:
    if level or not (mod == "homeassistant" or mod.startswith("homeassistant.")):
        return []
    out = []
    if not names:                                              # import homeassistant.x [as y]
        if mod not in HA_ALLOWED:
            out.append(f"import {mod}")
        elif HA_ALLOWED[mod] is not None:
            out.append(f"import {mod} (only 'from {mod} import ...' of {sorted(HA_ALLOWED[mod])})")
        return out
    for nm in names:
        full = f"{mod}.{nm}"
        if full in HA_ALLOWED and HA_ALLOWED[full] is None:     # from homeassistant.helpers import event
            continue
        if mod in HA_ALLOWED and (HA_ALLOWED[mod] is None or nm in HA_ALLOWED[mod]):
            continue
        out.append(f"from {mod} import {nm}")
    return out


def banned_import(mod: str, names: tuple[str, ...], level: int) -> list[str]:
    out = []
    cands = [mod] + [f"{mod}.{n}" for n in names]
    for c in cands:
        for b in BANNED_IMPORTS:
            if level == 0 and (c == b or c.startswith(b + ".")):
                out.append(c)
        if "ecco_autonomy" in c.split("."):
            out.append(c)
        parts = c.split(".")
        if "ecco_core" in parts and parts[-1] in ("authority", "capability") and parts.index("ecco_core") == len(parts) - 2:
            out.append(c)
    return sorted(set(out))


def allowlist_violation(mod: str, names: tuple[str, ...], level: int, rel: str) -> str | None:
    """The positive non-homeassistant import allowlist; None = allowed."""
    if level:
        return None
    top = mod.split(".")[0]
    if top == "homeassistant" or top in RT_REPO or top in RT_THIRD_PARTY:
        return None
    if mod in RT_DENIED_SUBMODULES or any(f"{mod}.{n}" in RT_DENIED_SUBMODULES for n in names):
        return f"{mod} (denied submodule)"
    if top in RT_STDLIB_ANY:
        return None
    if top in RT_STORE_ONLY:
        return None if rel == "runtime/store.py" else f"{mod} (only in runtime/store.py)"
    if top in RT_ASYNC_ONLY:
        return None if rel in RT_ASYNC_FILES else f"{mod} (only in {' / '.join(RT_ASYNC_FILES)})"
    return f"{mod} (not on the runtime import allowlist)"


def str_constants(tree: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def call_name(f: ast.AST) -> str:
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")


def name_banned(nm: str) -> bool:
    return nm in BANNED_NAMES or nm.startswith(BANNED_PREFIXES) or nm in LOG_FILE_HANDLERS or nm in DUNDER_BANNED


def write_calls(tree: ast.AST) -> list[str]:
    out = []
    os_aliases = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names if a.name == "os"}
    os_names = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "os" for a in n.names}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Name) and f.id == "open":
            mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
            if mode is not None and not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                                         and set(mode.value) <= {"r", "b", "t"}):
                out.append(f"open(mode={ast.unparse(mode)})")
        elif isinstance(f, ast.Name) and f.id in os_names and f.id in OS_WRITES:
            out.append(f"os.{f.id}")
        elif isinstance(f, ast.Attribute):
            if f.attr in WRITE_ATTRS:
                out.append(f".{f.attr}()")
            if f.attr == "open" and not (isinstance(f.value, ast.Name) and f.value.id in os_aliases):
                mode = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg == "mode"), None)
                if mode is not None and not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                                             and set(mode.value) <= {"r", "b", "t"}):
                    out.append(f".open({ast.unparse(mode)})")
            if isinstance(f.value, ast.Name) and f.value.id in os_aliases and f.attr in OS_WRITES:
                out.append(f"os.{f.attr}")
            if isinstance(f.value, ast.Name) and f.value.id == "sqlite3" and f.attr == "connect":
                out.append("sqlite3.connect")
            if isinstance(f.value, ast.Name) and f.value.id in ("shutil", "tempfile"):
                out.append(f"{f.value.id}.{f.attr}")
    return out


def name_violations(tree: ast.AST) -> list[str]:
    """[3]: banned attribute / called / imported names, state and bus writes by receiver, dynamic calls, getattr with a
    computed or banned name, dunder access, string constants equal to a banned name."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and name_banned(n.attr):
            out.append(f".{n.attr}")
        elif isinstance(n, ast.Name) and name_banned(n.id):
            out.append(n.id)
        elif isinstance(n, ast.alias) and name_banned((n.asname or n.name).split(".")[-1]):
            out.append(f"import {n.name}")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and name_banned(n.value):
            out.append(f"string {n.value!r}")
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in STATE_BUS_WRITES:
            recv = f.value
            rname = recv.attr if isinstance(recv, ast.Attribute) else (recv.id if isinstance(recv, ast.Name) else "")
            if rname in ("states", "bus"):
                out.append(f"{rname}.{f.attr}()")
        if isinstance(f, ast.Name) and f.id in DYNAMIC_CALLS:
            out.append(f"{f.id}()")
        if isinstance(f, ast.Name) and f.id in ("getattr", "hasattr"):
            arg = n.args[1] if len(n.args) > 1 else None
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) or name_banned(arg.value) \
                    or arg.value in PROVENANCE_NAMES or arg.value.startswith("_"):
                out.append(f"{f.id}({ast.unparse(arg) if arg is not None else '?'})")
    return out


def provenance_violations(tree: ast.AST) -> list[str]:
    """[8]: no way to widen accept_provenance or to mint a decision in code."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.keyword) and n.arg == "accept_provenance":
            out.append("keyword accept_provenance")
        elif isinstance(n, (ast.Name, ast.arg)) and getattr(n, "id", getattr(n, "arg", None)) == "accept_provenance":
            out.append("name accept_provenance")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and (n.value == "accept_provenance" or n.value in PROVENANCE_NAMES):
            out.append(f"string {n.value!r}")
        elif isinstance(n, ast.Name) and n.id in PROVENANCE_NAMES:
            out.append(f"name {n.id}")
        elif isinstance(n, ast.Attribute) and n.attr in PROVENANCE_NAMES:
            out.append(f".{n.attr}")
        elif isinstance(n, ast.alias) and (n.asname or n.name).split(".")[-1] in PROVENANCE_NAMES | DECISION_BUILDERS:
            out.append(f"import {n.name}")
        if not isinstance(n, ast.Call):
            continue
        nm = call_name(n.func)
        if nm in DECISION_BUILDERS:
            out.append(f"{nm}() builds a decision in code")
        if nm in NO_STAR_CALLS and (any(isinstance(a, ast.Starred) for a in n.args) or any(k.arg is None for k in n.keywords)):
            out.append(f"{nm}(*/**) expansion")
        if nm in ACCEPT_POSITIONAL_LIMIT and len(n.args) > ACCEPT_POSITIONAL_LIMIT[nm]:
            out.append(f"{nm}() with {len(n.args)} positional arguments (at most {ACCEPT_POSITIONAL_LIMIT[nm]})")
        if nm == "DecisionSet" and (n.args or n.keywords):
            out.append("DecisionSet(...) built in code (load with DecisionSet.from_mapping(..., source='site_local'))")
        if nm == "from_mapping":
            src = [k.value for k in n.keywords if k.arg == "source"]
            if len(n.args) > 1 or len(src) != 1 or not (isinstance(src[0], ast.Constant) and src[0].value == "site_local"):
                out.append("from_mapping() without the keyword source='site_local'")
    return out


def event_helper_calls(tree: ast.AST) -> list[tuple[str, str]]:
    """(helper name, first argument as text) of every call to a helpers.event function or a bus listen method."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            nm = call_name(n.func)
            if nm in EVENT_HELPER_SITES or (nm in BUS_LISTEN_NAMES and isinstance(n.func, ast.Attribute)):
                out.append((nm, ast.unparse(n.args[0]) if n.args else ""))
    return out


def tests_imports(mod: str, names: tuple[str, ...], level: int) -> bool:
    return "tests" in mod.split(".") or (not mod and "tests" in names) or (level and "tests" in names and not mod)


def scan_integration(files: list[Path], base: Path, label: str) -> None:
    """The integration rules for the non-vendored files of a package rooted at `base`."""
    viol: dict[str, list] = {k: [] for k in ("ha", "init_ha", "runtime_ha", "names", "imports", "allow", "asyncio", "os_sqlite",
                                             "strings", "writes", "accept", "tests", "parse")}
    helper_calls: list[tuple[str, str, str]] = []
    for p in files:
        rel = p.relative_to(base).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            viol["parse"].append(f"{rel}: {type(exc).__name__}")
            continue
        helper_calls += [(rel, nm, arg) for nm, arg in event_helper_calls(tree)]
        mod_level = module_level_nodes(tree)
        for mod, names, level, node in imported(tree):
            viol["ha"] += [f"{rel}: {v}" for v in ha_violations(mod, names, level)]
            is_ha = level == 0 and (mod == "homeassistant" or mod.startswith("homeassistant."))
            if rel == "__init__.py" and is_ha and id(node) in mod_level:
                viol["init_ha"].append(f"{rel}: {mod}")
            if rel.startswith("runtime/") and is_ha:
                viol["runtime_ha"].append(f"{rel}: {mod}")
            viol["imports"] += [f"{rel}: {b}" for b in banned_import(mod, names, level)]
            a = allowlist_violation(mod, names, level, rel)
            if a:
                viol["allow"].append(f"{rel}: {a}")
            tops = {mod.split(".")[0]} if level == 0 else set()
            if "asyncio" in tops and rel not in RT_ASYNC_FILES:
                viol["asyncio"].append(rel)
            if tops & {"os", "sqlite3"} and rel != "runtime/store.py":
                viol["os_sqlite"].append(f"{rel}: {sorted(tops & {'os', 'sqlite3'})}")
            if tests_imports(mod, names, level):
                viol["tests"].append(f"{rel}: {'.' * level}{mod} {list(names)}")
        viol["names"] += [f"{rel}: {v}" for v in name_violations(tree)]
        viol["accept"] += [f"{rel}: {v}" for v in provenance_violations(tree)]
        for s in str_constants(tree):
            low = s.lower()
            viol["strings"] += [f"{rel}: {b}" for b in BANNED_STRINGS if b in low]
        if rel != "runtime/store.py":
            viol["writes"] += [f"{rel}: {w}" for w in write_calls(tree)]
    n = len(files)
    check(f"{label}: every source file parses ({n} files)", not viol["parse"], str(viol["parse"][:5]))
    check(f"{label}: Home Assistant imports are within the positive allowlist ({n} files)", not viol["ha"], str(viol["ha"][:5]))
    check(f"{label}: __init__.py has no module-level homeassistant import", not viol["init_ha"], str(viol["init_ha"]))
    check(f"{label}: runtime/*.py imports no homeassistant at all", not viol["runtime_ha"], str(viol["runtime_ha"][:5]))
    check(f"{label}: no banned attribute, called or imported name (service calls, state / bus writes, fires, registry / "
          "statistics writes, storage, RestoreEntity, log file handlers, dynamic calls, computed getattr, dunders)",
          not viol["names"], str(viol["names"][:5]))
    check(f"{label}: no banned import (network, process, serial, dynamic import, os back ends, ecco_autonomy, "
          "ecco_core.authority / capability, storage)", not viol["imports"], str(viol["imports"][:5]))
    check(f"{label}: every other import is on the positive allowlist (pure stdlib; store-only and async-only modules in "
          "their files; voluptuous; the repository)", not viol["allow"], str(viol["allow"][:5]))
    check(f"{label}: asyncio only in __init__.py and coordinator.py", not viol["asyncio"], str(viol["asyncio"]))
    check(f"{label}: os and sqlite3 only in runtime/store.py", not viol["os_sqlite"], str(viol["os_sqlite"]))
    check(f"{label}: production code imports no tests package", not viol["tests"], str(viol["tests"][:5]))
    check(f"{label}: no banned string (write / control vocabulary, ACS1 / Free Power / Dump / recovery names)",
          not viol["strings"], str(viol["strings"][:5]))
    check(f"{label}: file writes only in runtime/store.py", not viol["writes"], str(viol["writes"][:5]))
    check(f"{label}: provenance is never widened at run time (no accept_provenance keyword, positional or * / ** route; no "
          "provenance constant; no decision built in code; from_mapping only with source='site_local')",
          not viol["accept"], str(viol["accept"][:5]))
    if files:
        sites = {nm: [f"{r}:{a}" for r, n_, a in helper_calls if n_ == nm] for nm in EVENT_HELPER_SITES}
        bus = [(r, n_, a) for r, n_, a in helper_calls if n_ in BUS_LISTEN_NAMES]
        check(f"{label}: the event helpers are called from one place each, in {EVENT_HELPER_FILE} (the one timer, the one "
              "state listener, the poll-driven step's one-shot; A23), and the only bus listener is the one-shot "
              "homeassistant_started listener",
              all(len(v) == EVENT_HELPER_SITES[nm] and all(s.startswith(EVENT_HELPER_FILE + ":") for s in v)
                  for nm, v in sites.items())
              and bus == [(EVENT_HELPER_FILE, "async_listen_once", "EVENT_HOMEASSISTANT_STARTED")], f"{sites} {bus}")


def scan_platforms_and_manifest(base: Path, label: str, any_source: bool) -> None:
    every = [p for p in base.rglob("*") if p.is_file() and not is_test_path(p.relative_to(base).parts)]
    files = [p for p in every if "_vendor" not in p.relative_to(base).parts]
    top_py = {p.stem for p in files if p.suffix == ".py" and p.parent == base}
    top_pkgs = {p.parent.name for p in files if p.name == "__init__.py" and p.parent.parent == base}
    bad = sorted(((top_py | top_pkgs) & HA_PLATFORMS) - ALLOWED_PLATFORMS)
    check(f"{label}: platforms are only sensor / binary_sensor (modules or packages)", not bad, str(bad))
    svc = [p.relative_to(base).as_posix() for p in files if p.name in ("services.yaml", "services.py")
           or (p.name == "__init__.py" and p.parent.name == "services")]
    check(f"{label}: no services.yaml or services.py", not svc, str(svc))
    binaries = [p.relative_to(base).as_posix() for p in every if p.suffix.lower() in BINARY_SUFFIXES
                or (p.suffix.lower() == ".pyc" and p.parent.name != "__pycache__")]
    check(f"{label}: no compiled or path-hook file (.so / .pyd / .pth / .dll, a .pyc outside __pycache__)", not binaries,
          str(binaries[:5]))
    for p in files:
        if p.suffix in (".json", ".yaml", ".yml"):
            low = p.read_text(encoding="utf-8", errors="replace").lower()
            hits = [b for b in BANNED_STRINGS if b in low]
            check(f"{label}: {p.relative_to(base).as_posix()} has no banned string", not hits, str(hits))
    man = base / "manifest.json"
    if any_source:
        ok, detail = False, "missing"
        if man.is_file():
            try:
                m = json.loads(man.read_text(encoding="utf-8"))
                ok = (isinstance(m, dict) and m.get("requirements") == [] and isinstance(m.get("dependencies", []), list)
                      and set(m.get("dependencies", [])) <= {"recorder"} and m.get("iot_class") == "calculated"
                      and "services" not in m)
                detail = json.dumps({k: m.get(k) for k in ("requirements", "dependencies", "iot_class")}) if isinstance(m, dict) else "not an object"
            except ValueError as exc:
                detail = f"invalid JSON: {exc}"
        check(f"{label}: manifest.json has requirements [], dependencies within ['recorder'], iot_class 'calculated', "
              "no 'services'", ok, detail)
    else:
        check(f"{label}: no source yet, so no manifest is required (vacuous)", True)


def scan_vendor(vendor: Path) -> None:
    files = sorted(p for p in vendor.rglob("*.py"))
    rels = [p.relative_to(vendor).as_posix() for p in files]
    check("_vendor: has files", bool(files), str(vendor))
    absolute, bad_imp, vocab, calls = [], [], [], []
    for p, rel in zip(files, rels):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for mod, names, level, _node in imported(tree):
            if level == 0 and mod.split(".")[0] in ("intelligence", "ecco_core"):
                absolute.append(f"{rel}: {mod}")
            tops = {mod.split(".")[0]} if level == 0 else set()
            allowed = {"sqlite3"} if rel == "intelligence/scorecard.py" else set()
            for t in tops:
                if t in I_BAD and t not in allowed:
                    bad_imp.append(f"{rel}: {t}")
            bad_imp += [f"{rel}: {b}" for b in banned_import(mod, names, level) if b.split(".")[0] not in allowed]
        for s in str_constants(tree):
            if len(s) < 200 and any(v in s.lower() for v in I_VOCAB):
                vocab.append(f"{rel}: {s[:30]}")
        calls += [f"{rel}: {call_name(n.func)}()" for n in ast.walk(tree) if isinstance(n, ast.Call) and call_name(n.func) in I_CALLS]
    check("_vendor: no absolute intelligence / ecco_core import remains at any depth", not absolute, str(absolute[:5]))
    check("_vendor: the Intelligence import rules hold (sqlite3 only in intelligence/scorecard.py)", not bad_imp, str(bad_imp[:5]))
    check("_vendor: no control vocabulary in string constants", not vocab, str(vocab[:5]))
    check("_vendor: no process, exec / eval / compile or dynamic-import call", not calls, str(calls[:5]))
    forbidden = [r for r in rels if r.startswith("ecco_autonomy/") or r in ("ecco_core/authority.py", "ecco_core/capability.py")
                 or any(part in ("tests", "tools", "prototypes", "profiles") for part in r.split("/"))]
    check("_vendor: no ecco_autonomy, ecco_core/authority.py, ecco_core/capability.py, tests, tools, prototypes or profiles",
          not forbidden, str(forbidden[:5]))


def check_manifest_and_sums(out: Path, pkg: Path) -> None:
    vm, sums = out / "VENDOR_MANIFEST.json", out / "SHA256SUMS"
    check("build: VENDOR_MANIFEST.json and SHA256SUMS exist", vm.is_file() and sums.is_file())
    if not (vm.is_file() and sums.is_file()):
        return
    bad = []
    listed = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _sep, rel = line.partition("  ")
        rel = rel.strip().lstrip("*")
        target = out / rel
        listed += 1
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest.strip().lower():
            bad.append(rel)
    built = {p.relative_to(out).as_posix() for p in pkg.rglob("*") if p.is_file()}
    sums_set = {ln.partition("  ")[2].strip().lstrip("*") for ln in sums.read_text(encoding="utf-8").splitlines() if ln.strip()}
    check(f"build: SHA256SUMS matches every listed file ({listed}) and lists every built file", not bad and built <= sums_set,
          str(bad[:3] + sorted(built - sums_set)[:3]))
    try:
        man = json.loads(vm.read_text(encoding="utf-8"))
        text = json.dumps(man)
        vend = {p.relative_to(pkg).as_posix() for p in (pkg / "_vendor").rglob("*.py")} if (pkg / "_vendor").is_dir() else set()
        check("build: VENDOR_MANIFEST.json names every vendored module", all(v in text for v in vend), str(sorted(vend)[:3]))
    except ValueError as exc:
        check("build: VENDOR_MANIFEST.json is valid JSON", False, str(exc))


def tracked_vendor() -> list[str]:
    try:
        p = subprocess.run(["git", "ls-files", "--", "custom_components"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if p.returncode == 0:
            return [ln for ln in p.stdout.splitlines() if "/_vendor/" in ln or ln.startswith("_vendor/")]
    except (OSError, subprocess.SubprocessError):
        pass
    return [p.relative_to(ROOT).as_posix() for p in CC.rglob("_vendor")] if CC.is_dir() else []


# ---------------------------------------------------------------------------------------------------------------------
print("== [1]-[8] the source tree")
src_files = sorted(p for p in PKG.rglob("*.py")
                   if not is_test_path(p.relative_to(PKG).parts) and "_vendor" not in p.relative_to(PKG).parts) if PKG.is_dir() else []
print(f"  ({len(src_files)} non-test source file(s) under custom_components/ecco_intelligence)")
scan_integration(src_files, PKG, "source")
if PKG.is_dir():
    scan_platforms_and_manifest(PKG, "source", bool(src_files))
hacs = [p.relative_to(ROOT).as_posix() for p in CC.rglob("hacs.json")] if CC.is_dir() else []
check("no hacs.json anywhere under custom_components/", not hacs, str(hacs))
check("_vendor/ exists only in a build output: none is tracked or present in the source tree", not tracked_vendor()
      and not (PKG / "_vendor").exists(), str(tracked_vendor()[:3]))
check("the suite really ran its rules (the allowlists and banned sets are non-empty)",
      len(HA_ALLOWED) == 14 and len(BANNED_NAMES) >= 21 and len(BANNED_STRINGS) == 16 and len(RT_STDLIB_ANY) >= 20
      and len(PROVENANCE_NAMES) == 6 and len(ACCEPT_POSITIONAL_LIMIT) == 8)
_selftest = ast.parse("hass.states.set('a', 1)\ngetattr(hass, 'serv' 'ices')\nCycleInputs(*a)\n"
                      "for _i in ():\n    import homeassistant.core\n")
check("the rules catch their own examples (self-test)",
      any("states.set" in v for v in name_violations(_selftest)) and any("services" in v for v in name_violations(_selftest))
      and any("expansion" in v for v in provenance_violations(_selftest)) and len(module_level_nodes(_selftest)) == 1)

print("== [9] the built artefact")
if BUILD_TOOL.is_file():
    with tempfile.TemporaryDirectory(prefix="ecco_intel_build_") as td:
        out = Path(td) / "out"
        p = subprocess.run([sys.executable, "-I", str(BUILD_TOOL), "--out", str(out), "--git-sha", "0000000"],
                           cwd=ROOT, capture_output=True, text=True, timeout=600)
        check("build: the frozen command line exits 0", p.returncode == 0, (p.stdout + p.stderr)[-400:])
        bpkg = out / "custom_components" / "ecco_intelligence"
        check("build: writes custom_components/ecco_intelligence/", bpkg.is_dir())
        if bpkg.is_dir():
            bfiles = sorted(q for q in bpkg.rglob("*.py") if "_vendor" not in q.relative_to(bpkg).parts
                            and not is_test_path(q.relative_to(bpkg).parts))
            scan_integration(bfiles, bpkg, "built")
            scan_platforms_and_manifest(bpkg, "built", bool(bfiles))
            absolute = [f"{q.relative_to(bpkg).as_posix()}: {m}" for q in bfiles
                        for m, _n, lv, _nd in imported(ast.parse(q.read_text(encoding="utf-8")))
                        if lv == 0 and m.split(".")[0] in ("intelligence", "ecco_core", "ecco_autonomy")]
            check("built: the integration files import intelligence / ecco_core only through _vendor (relative)", not absolute,
                  str(absolute[:5]))
            if (bpkg / "_vendor").is_dir():
                scan_vendor(bpkg / "_vendor")
            else:
                check("built: a _vendor directory exists", False)
            check_manifest_and_sums(out, bpkg)
            check("built: no hacs.json in the artefact", not list(out.rglob("hacs.json")))
    probe = ROOT / "custom_components" / f"_refusal_probe_{os.getpid()}"
    existed = probe.exists()
    try:
        inside = subprocess.run([sys.executable, "-I", str(BUILD_TOOL), "--out", str(probe)],
                                cwd=ROOT, capture_output=True, text=True, timeout=120)
        check("build: an --out inside the repository is refused", inside.returncode != 0 and not probe.exists())
    finally:
        if probe.exists() and not existed:              # only ever the probe path this run created
            shutil.rmtree(probe)
else:
    check("build: tools/build_ha_integration.py does not exist yet (vacuous)", True)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the runtime boundaries:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all runtime boundary checks passed")
