#!/usr/bin/env python3
"""Static repository checks for ECCO Pro.

This intentionally validates structure/syntax only. It does not connect to Home
Assistant, ESPHome, InfluxDB or the inverter and therefore cannot replace live
hardware verification.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _safe_paths import UnsafePathError, resolve_source  # noqa: E402
from validate_capability_registry import validate as validate_capability_registry  # noqa: E402
from validate_system_health_checks import validate as validate_health_checks  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
CHECKED = {
    "yaml": 0,
    "python": 0,
    "json": 0,
    "flux": 0,
    "text": 0,
    "manifest_refs": 0,
    "capability_registry_records": 0,
    "health_check_records": 0,
    "health_reason_codes": 0,
}

TEXT_SUFFIXES = {
    ".yaml",
    ".yml",
    ".py",
    ".json",
    ".flux",
    ".md",
    ".ps1",
    ".sh",
    ".txt",
    ".toml",
}
SUSPICIOUS_TEXT = {
    chr(0x00C2): "possible UTF-8 mojibake marker U+00C2",
    chr(0x00C3): "possible UTF-8 mojibake marker U+00C3",
    chr(0xFFFD): "Unicode replacement character U+FFFD",
}


class TaggedSafeLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant/ESPHome custom !tags."""


def _construct_unknown(loader: TaggedSafeLoader, tag_suffix: str, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


TaggedSafeLoader.add_multi_constructor("!", _construct_unknown)


def fail(path: Path | str, message: str) -> None:
    ERRORS.append(f"{path}: {message}")


def validate_text(path: Path) -> None:
    rel = path.relative_to(ROOT)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        fail(rel, f"not valid UTF-8: {exc}")
        return

    for marker, message in SUSPICIOUS_TEXT.items():
        if marker in text:
            fail(rel, message)

    for idx, char in enumerate(text):
        codepoint = ord(char)
        if codepoint < 32 and char not in "\t\n\r":
            fail(rel, f"unexpected control character U+{codepoint:04X} at character {idx}")
            break

    CHECKED["text"] += 1


def validate_yaml(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            list(yaml.load_all(handle, Loader=TaggedSafeLoader))
        CHECKED["yaml"] += 1
    except Exception as exc:  # noqa: BLE001 - report all parser errors
        fail(path.relative_to(ROOT), f"YAML parse failed: {exc}")


def validate_python(path: Path) -> None:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        CHECKED["python"] += 1
    except Exception as exc:  # noqa: BLE001
        fail(path.relative_to(ROOT), f"Python parse failed: {exc}")


def validate_json(path: Path) -> None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        CHECKED["json"] += 1
    except Exception as exc:  # noqa: BLE001
        fail(path.relative_to(ROOT), f"JSON parse failed: {exc}")


def validate_flux(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # Lightweight checks only; InfluxDB remains the authoritative Flux parser.
    required = ["option task", "from(", "to("] if "tasks" in path.parts else []
    for token in required:
        if token not in text:
            fail(path.relative_to(ROOT), f"Flux sanity check missing {token!r}")
    CHECKED["flux"] += 1


def walk_repo() -> None:
    # node_modules: local npm install output for the frontend/ card
    # packages - never committed (see each package's own .gitignore), and
    # third-party package files (localised strings, minified bundles, etc.)
    # routinely trip validate_text's UTF-8/mojibake heuristics with false
    # positives that have nothing to do with this repo's own content.
    # .esphome: generated ESPHome build/toolchain output, already excluded
    # from the repository entirely by .gitignore (".esphome/", "**/.esphome/") -
    # ignoring it here just keeps the validator's own file walk consistent
    # with what is actually tracked.
    ignored_parts = {".git", ".venv", "venv", "__pycache__", "dist", "node_modules", ".esphome"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in ignored_parts for part in path.parts):
            continue

        suffix = path.suffix.lower()
        if suffix in TEXT_SUFFIXES:
            validate_text(path)
        if suffix in {".yaml", ".yml"}:
            validate_yaml(path)
        elif suffix == ".py":
            validate_python(path)
        elif suffix == ".json":
            validate_json(path)
        elif suffix == ".flux":
            validate_flux(path)


def validate_version_references() -> None:
    version_path = ROOT / "VERSION.yaml"
    if not version_path.exists():
        fail("VERSION.yaml", "missing")
        return
    data = yaml.safe_load(version_path.read_text(encoding="utf-8")) or {}

    def recurse(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {
                    "path",
                    "core_package",
                    "free_power_schedule",
                    "battery_outlook_readback",
                    "export_config",
                    "battery_outlook_task",
                    "dashboard",
                    "firmware",
                } and isinstance(child, str):
                    if "/" in child and not child.startswith("/") and child != "known-good-2026-09-15-v7.11.0":
                        candidate = ROOT / child
                        CHECKED["manifest_refs"] += 1
                        if not candidate.exists():
                            fail("VERSION.yaml", f"referenced path does not exist: {child}")
                recurse(child)
        elif isinstance(value, list):
            for child in value:
                recurse(child)

    recurse(data)


def validate_deployment_sources() -> None:
    manifest = ROOT / "deployment" / "ha-manifest.yaml"
    if not manifest.exists():
        fail(manifest.relative_to(ROOT), "missing")
        return
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}

    def recurse(value):
        if isinstance(value, dict):
            src = value.get("source")
            if isinstance(src, str):
                CHECKED["manifest_refs"] += 1
                # Containment: in-repo, no '..', no symlink, approved directory/suffix (git-tracked is checked by the bundle builder).
                try:
                    resolve_source(ROOT, src, require_tracked=False)
                except UnsafePathError as exc:
                    fail(manifest.relative_to(ROOT), str(exc))
            for child in value.values():
                recurse(child)
        elif isinstance(value, list):
            for child in value:
                recurse(child)

    recurse(data)


def validate_inverter_capability_registry() -> None:
    """Delegates to tools/validate_capability_registry.py - see
    docs/INVERTER_CAPABILITY_REGISTRY.md section 12 ('integrate with the
    existing ECCO validator where practical')."""
    registry_path = ROOT / "registry" / "inverter_capabilities.yaml"
    if not registry_path.exists():
        # Registry is new as of Task 005; treat as optional rather than
        # a hard requirement so this validator keeps working on branches
        # that predate it.
        return
    errors = validate_capability_registry(registry_path)
    for error in errors:
        fail(registry_path.relative_to(ROOT), error)
    if not errors:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        CHECKED["capability_registry_records"] = len(data.get("capabilities") or [])


def validate_system_health_registry() -> None:
    """Delegates to tools/validate_system_health_checks.py - see
    docs/SYSTEM_HEALTH_ARCHITECTURE.md section 16 ('integrated into
    tools/validate_repo.py')."""
    checks_path = ROOT / "registry" / "system_health_checks.yaml"
    reason_codes_path = ROOT / "registry" / "health_reason_codes.yaml"
    if not checks_path.exists() and not reason_codes_path.exists():
        # Health registry is new as of Task 006; treat as optional rather
        # than a hard requirement so this validator keeps working on
        # branches that predate it.
        return
    errors = validate_health_checks(checks_path, reason_codes_path)
    for error in errors:
        fail(checks_path.relative_to(ROOT), error)
    if not errors:
        checks_data = yaml.safe_load(checks_path.read_text(encoding="utf-8")) or {}
        reason_data = yaml.safe_load(reason_codes_path.read_text(encoding="utf-8")) or {}
        CHECKED["health_check_records"] = len(checks_data.get("checks") or [])
        CHECKED["health_reason_codes"] = len(reason_data.get("reason_codes") or [])


def main() -> int:
    walk_repo()
    validate_version_references()
    validate_deployment_sources()
    validate_inverter_capability_registry()
    validate_system_health_registry()

    if ERRORS:
        print("ECCO repository validation FAILED")
        for error in ERRORS:
            print(f" - {error}")
        return 1

    print("ECCO repository validation PASSED")
    print(", ".join(f"{name}={count}" for name, count in CHECKED.items()))
    print("Note: static validation does not replace Home Assistant/ESPHome/InfluxDB or hardware testing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
