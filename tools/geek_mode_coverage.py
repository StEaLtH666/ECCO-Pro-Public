#!/usr/bin/env python3
"""Geek Mode information coverage: the catalogue and the ledger for ONE view (the ECCO Intelligence SHADOW tab).

    python tools/geek_mode_coverage.py                 # (re)write the catalogue, the ledger (JSON and Markdown)
    python tools/geek_mode_coverage.py --check         # regenerate in memory and compare with the committed files (exit 1 on drift)
    python tools/geek_mode_coverage.py --no-shape      # leave the live comparison out (default: the committed live-shape copy)
    python tools/geek_mode_coverage.py --shape FILE    # compare with another live shape listing

What it does, in order:
  1. COMPUTES the available universe from code, never by hand: the contract (intelligence/advisory_contract.py: ENTITY_IDS, the
     per-entity attribute lists, the entity payloads the contract builders produce for the contract fixtures, the block keys),
     the advice shapes (the dict literals of the advisors and of the shadow cycle, read as source, not run), the presentation
     package and its companions (home-assistant/packages), the integration (custom_components/ecco_intelligence: names, device
     classes, options, units, the diagnostics download), the standalone dashboard and the Production card's read lists.
  2. Builds the catalogue `ecco-geek-catalogue/1` (frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json) from that
     universe and the plain-words texts in tools/geek_mode_texts_intelligence.py. A universe member without a text, or a text
     without a universe member, is an error: the catalogue cannot silently lag the code, and an invented entry cannot linger.
  3. Builds the information coverage ledger (docs/product-ui/GEEK_MODE_COVERAGE_LEDGER_intelligence.md and its machine form
     frontend/ecco-mode-shell/catalogue/intelligence.ledger.json): every source and attribute as COVERED, every exception with its
     reason, and (with a live shape listing) the live comparison: UNDECLARED, NOT_PRESENT_LIVE, NOT_CHECKED_LIVE.

Read-only with respect to everything except the three generated files; no network; standard library plus PyYAML. The live shape
listing holds entity ids, attribute names, types and sizes only: no value.

Exit codes: 0 fine; 1 drift, a coverage finding or an invalid catalogue (the lines say which); 2 bad usage.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

TOOLS_DIR = Path(__file__).resolve().parent
REPO = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

SCHEMA = "ecco-geek-catalogue/1"
LEDGER_SCHEMA = "ecco-geek-ledger/1"
VIEW_ID = "intelligence"
CATALOGUE_REL = "frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json"
LEDGER_JSON_REL = "frontend/ecco-mode-shell/catalogue/intelligence.ledger.json"
LEDGER_MD_REL = "docs/product-ui/GEEK_MODE_COVERAGE_LEDGER_intelligence.md"
SHAPE_REL = "frontend/ecco-mode-shell/catalogue/live-shape.intelligence.json"
FIXTURE_DIR_REL = "frontend/ecco-mode-shell/test/fixtures"
FIXTURE_NAMES = ("healthy", "mixed", "stale", "unavailable", "self-test-failed", "paused", "watchdog-stale", "extras", "contract-breach")

PRIORITIES = ("headline", "normal", "obscure")
ORIGINS = ("integration", "package", "dashboard")
SEVERITIES = ("critical", "warning", "info")
EXCEPTION_REASONS = ("secret", "privacy", "unsupported_source", "not_exposed_in_states")
COVERAGE_STATES = ("COVERED", "EXCEPTION")
LIVE_STATES = ("PRESENT_LIVE", "NOT_PRESENT_LIVE", "NOT_CHECKED_LIVE", "UNDECLARED")
# the words a Geek Mode row may carry for its data (the card shows each in words and with an icon, never colour alone)
HONESTY_STATES = ("LIVE", "STALE", "UNAVAILABLE", "UNKNOWN", "NOT_MEASURED", "SIMULATED", "UNVERIFIED", "WITHHELD")
ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
SOURCE_ID_RE = re.compile(r"^[a-z0-9_.]+$")
ATTR_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)?$")
# review round 6: a catalogue key pattern is a PLAIN FRAGMENT, the same rule as the card's (frontend/ecco-mode-shell/ecco-mode-shell.js EXTRA_FRAGMENT): 1 to 80 lower-case letters, digits or
# underscores, at most 40 of them, matched as a part of a key name and never as an expression. Match it with fullmatch: a Python "$" also accepts a newline at the end ("token\n").
PATTERN_RE = re.compile(r"[a-z0-9_]{1,80}")
PATTERN_MAX_COUNT = 40
PREFIX_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+_$")

# HA entity domains whose entities carry a state a reader can show; the prefix `ecco_intel_` in each is discovered automatically
DISCOVER_DOMAINS = ("automation", "binary_sensor", "button", "counter", "datetime", "event", "input_boolean", "input_datetime",
                    "input_number", "input_select", "input_text", "number", "script", "select", "sensor", "switch", "text",
                    "timer", "update")
DISCOVER_NAME_PREFIX = "ecco_intel_"

# What Home Assistant itself adds to an entity of a domain (beyond what the repository defines). The live shape listing is the net
# that catches a difference: a live attribute that is neither declared by code nor in this table is UNDECLARED.
HA_DOMAIN_ATTRIBUTES = {
    "automation": ("current", "id", "last_triggered", "mode"),
    "input_boolean": ("editable",),
    "input_number": ("editable", "initial"),
}
# keys of a package helper's YAML that become attributes of its entity
YAML_HELPER_ATTRIBUTES = ("icon", "min", "max", "step", "mode", "unit_of_measurement")


class UniverseError(Exception):
    """The code and the packages disagree with each other, or a source cannot be read: no catalogue can be trusted."""


class CoverageError(Exception):
    """The texts and the universe disagree (an uncatalogued member or an orphan text)."""


# ---------------------------------------------------------------------------------------------------------------------
# reading code as data
# ---------------------------------------------------------------------------------------------------------------------

def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError as exc:
        raise UniverseError(f"cannot read {rel}: {exc}") from None


def _tree(root: Path, rel: str) -> ast.Module:
    try:
        return ast.parse(_read(root, rel), filename=rel)
    except SyntaxError as exc:
        raise UniverseError(f"{rel} does not parse: {exc}") from None


def _str_keys(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Dict) and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in node.keys):
        return [k.value for k in node.keys]  # type: ignore[union-attr]
    return None


def _strs(node: ast.AST) -> list[str] | None:
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]  # type: ignore[union-attr]
    return None


def _assigned(tree: ast.Module, name: str):
    """Every value assigned to a plain name anywhere in the module (module level and inside functions), in source order."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            out.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
            out.append(node.value)
    return out


def dict_literal_keys(tree: ast.Module, name: str, rel: str) -> set[str]:
    """The union of the string keys of every `name = {...}` dict literal in the module."""
    keys: set[str] = set()
    for v in _assigned(tree, name):
        k = _str_keys(v)
        if k:
            keys |= set(k)
    if not keys:
        raise UniverseError(f"{rel}: no `{name} = {{...}}` dict literal with string keys was found (the advice shape moved; "
                            f"update tools/geek_mode_coverage.py)")
    return keys


def _slug(text: str) -> str:
    """Home Assistant's entity-id slug of a name: lower case, every run of other characters one underscore."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates Home Assistant's custom tags (!include, !secret)."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None)


def _yaml(root: Path, rel: str):
    try:
        return yaml.load(_read(root, rel), Loader=_Loader)
    except yaml.YAMLError as exc:
        raise UniverseError(f"{rel} does not parse as YAML: {exc}") from None


def _load_module(root: Path, rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, root / rel)
    if spec is None or spec.loader is None:
        raise UniverseError(f"cannot load {rel}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_contract(root: Path):
    """Import intelligence.advisory_contract (and friends) from `root`. One root per process: a second, different root is refused."""
    r = str(root.resolve())
    have = sys.modules.get("intelligence")
    if have is not None and getattr(have, "__file__", None) and not str(Path(have.__file__).resolve()).startswith(r):
        raise UniverseError("the intelligence package is already imported from another repository root in this process")
    if r not in sys.path:
        sys.path.insert(0, r)
    try:
        ac = importlib.import_module("intelligence.advisory_contract")
        sd = importlib.import_module("intelligence.site_decisions")
        dp = importlib.import_module("intelligence.daily_plan")
    except Exception as exc:  # noqa: BLE001 - any import failure means the contract cannot be read
        raise UniverseError(f"cannot import the contract from {root}: {exc!r}") from None
    return ac, sd, dp


# ---------------------------------------------------------------------------------------------------------------------
# the universe
# ---------------------------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Ent:
    ident: str                     # stable ledger id: intel.status, intel.automation.alert_self_test_failed ...
    key: str                       # the contract key, the automation unique id or the helper key
    entity_id: str
    origin: str                    # integration | package
    kind: str                      # status | item | forecast | accuracy | data_quality | fresh | pause_helper | watchdog | automation | reserve_helper
    attrs: dict = dataclasses.field(default_factory=dict)    # path -> {"tags": [..], "shape": None|"ok"|"non_ok"}
    unit: str | None = None        # the unit of the entity's figure: the contract payload's `unit`, or the helper YAML's


@dataclasses.dataclass
class Universe:
    entities: list
    findings: list             # facts about the code the owner should know (strings); never silently dropped
    contract_version: str
    expected_update_s: float
    stale_after_s: float
    redact_keys: list          # the integration diagnostics' own TO_REDACT
    diag_sections: list        # top-level keys of the diagnostics download
    envelope_unpublished: list # AdvisoryEnvelope fields that no entity publishes
    site_reading_keys: list
    card_reads: dict           # {"attributes": [...], "blocks": {...}, "advice_keys": [...], "entities": [...]}
    dashboard_entities: list
    status_values: list
    dq_values: list
    decision_labels: list
    decision_titles: dict

    def by_ident(self) -> dict:
        return {e.ident: e for e in self.entities}


def _add(ent: Ent, path: str, tag: str, shape: str | None = None) -> None:
    a = ent.attrs.setdefault(path, {"tags": [], "shape": shape})
    if tag not in a["tags"]:
        a["tags"].append(tag)
    if shape is not None:
        a["shape"] = shape


def _integration_ha_attrs(root: Path, keys: tuple[str, ...]) -> dict:
    """{entity key: {HA standard attribute: tag}} from the integration classes (device class, options, unit) and entity_base (name)."""
    out = {k: {"friendly_name": "entity_base.py: the entity name"} for k in keys}
    for rel in ("custom_components/ecco_intelligence/sensor.py", "custom_components/ecco_intelligence/binary_sensor.py"):
        tree = _tree(root, rel)
        consts = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                s = _strs(node.value)
                if s is not None:
                    consts[node.targets[0].id] = s
        cls_keys: dict[str, set[str]] = {}
        cls_attrs: dict[str, dict[str, str]] = {}
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            attrs: dict[str, str] = {}
            ks: set[str] = set()
            for node in ast.walk(cls):
                names = []
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            names.append(t.id)
                        elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                            names.append(t.attr)
                for n in names:
                    for src, ha in (("_attr_device_class", "device_class"), ("_attr_options", "options"),
                                    ("_attr_native_unit_of_measurement", "unit_of_measurement")):
                        if n == src:
                            attrs[ha] = f"{rel.rsplit('/', 1)[1]}: {cls.name} sets {src}"
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_setup" \
                        and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    ks.add(node.args[1].value)
            cls_attrs[cls.name] = attrs
            cls_keys[cls.name] = ks
        # a class built for a constant tuple of keys: `[Cls(coordinator, k) for k in VALUE_KEYS]`
        for node in ast.walk(tree):
            if isinstance(node, ast.ListComp) and isinstance(node.elt, ast.Call) and isinstance(node.elt.func, ast.Name) \
                    and node.elt.func.id in cls_keys and node.generators and isinstance(node.generators[0].iter, ast.Name):
                cls_keys[node.elt.func.id] |= set(consts.get(node.generators[0].iter.id, ()))
        for cls, ks in cls_keys.items():
            for k in ks:
                if k in out:
                    out[k].update(cls_attrs[cls])
    return out


# The package files the tool models, and the top-level keys of each that it models. A package file is Home Assistant configuration: ANY other
# top-level key, and any other kind of entity inside a template block, may define a data point (a sensor, a number, a select, a button, an
# image, a script, a group ...) that the ledger would not account for, so the build FAILS CLOSED on it (review round 4): a new kind of entity
# has to be modelled here and catalogued (or excepted, with a reason) before the build passes. Nothing is skipped silently.
PACKAGE_MAIN_REL = "home-assistant/packages/ecco_intelligence.yaml"
PACKAGE_PREFS_REL = "home-assistant/packages/ecco_intelligence_prefs.yaml"
PACKAGE_DASHBOARD_REL = "home-assistant/packages/ecco_intelligence_dashboard.yaml"
PACKAGE_FILES = (PACKAGE_MAIN_REL, PACKAGE_PREFS_REL, PACKAGE_DASHBOARD_REL)
PACKAGE_MAIN_KEYS = ("input_boolean", "template", "automation")
PACKAGE_PREFS_KEYS = ("input_number",)
PACKAGE_DASHBOARD_KEYS = ("lovelace",)  # a dashboard registration: it defines no entity (the file says so; the tool holds it to that)
TEMPLATE_BLOCK_KEYS = ("binary_sensor",)


def _package_doc(root: Path, rel: str, allowed: tuple[str, ...]) -> dict:
    """The parsed package file, refused when it carries a top-level key the tool does not model."""
    doc = _yaml(root, rel)
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        raise UniverseError(f"{rel}: not a mapping of Home Assistant configuration keys")
    extra = sorted(str(k) for k in doc if k not in allowed)
    if extra:
        raise UniverseError(f"{rel}: the top-level key(s) {extra} define entities, or configuration, that tools/geek_mode_coverage.py does not model "
                            f"(it models {list(allowed)}): model and catalogue the new data points, or account for them as exceptions, before the build can pass")
    return doc


def _package_listing(root: Path) -> None:
    """The ECCO Intelligence package files are exactly the three the tool reads: a fourth file would define entities nobody accounted for.
    No other Home Assistant YAML file may define or name an ecco_intel_ data point either (review round 5: _foreign_definitions)."""
    d = root / "home-assistant" / "packages"
    found = sorted(f.name for f in d.glob("ecco_intel*")) if d.is_dir() else []
    known = sorted(Path(r).name for r in PACKAGE_FILES)
    if found != known:
        raise UniverseError(f"home-assistant/packages holds the ECCO Intelligence package files {found}, but tools/geek_mode_coverage.py models {known}: "
                            f"a package file it does not read can define data points the ledger would not account for")
    _foreign_definitions(root)


# Review round 5 (reviewer mutants L05 and L06). The listing above looks at the NAMES of the files in home-assistant/packages, so an ecco_intel_ entity that another
# package file defines (an input_text in ecco_dump_limits.yaml, a legacy template sensor in a new ecco_zz_probe.yaml) was neither COVERED nor an EXCEPTION, and --check
# still said the ledger matched. This reads the CONTENT of every other YAML file under home-assistant/ (packages, dashboards, prototypes) and refuses what defines or names
# one. A file that does not even spell ecco_intel is not parsed (it cannot define one), so the cost is a text search per file and a parse of the few that mention it.
HA_DIR_REL = "home-assistant"
# Review round 6 (reviewer mutant N-L11): whether a file is a DASHBOARD (where a `name:` is only a label, so the name check is skipped) is decided by where the file is, never by what it holds: a package that
# carries a `views:` key must not be taken for one. A dashboard is a file under home-assistant/dashboards/, one of the files named below, or the file the dashboard registration points at (see
# _registered_dashboard_files). A `views:` key in any file under home-assistant/packages/ is refused.
DASHBOARD_DIR_REL = "home-assistant/dashboards/"
PACKAGES_DIR_REL = "home-assistant/packages/"
PROTOTYPE_DASHBOARD_RELS = ("home-assistant/prototypes/intelligence-v1/ecco_intelligence_v1_prototype_dashboard.yaml",)
VIEWS_KEY_RE = re.compile(r"^views[ \t]*:", re.MULTILINE)
INTEL_OBJECT_RE = re.compile(r"^(?:[a-z_]+\.)?ecco_intel(?:_|$)")   # an object id, or a full entity id, in the ecco_intel family (not ecco_intelligence_*)
INTEL_MENTION_RE = re.compile(r"ecco[\W_]*intel", re.IGNORECASE)    # the cheap test: can this text spell such a name at all
DEFINING_VALUE_KEYS = ("unique_id", "object_id", "default_entity_id")  # their value IS (or becomes) an object id
NAMING_KEYS = ("name", "alias")  # in a package, the slug of one is the object id (a dashboard's `name:` is only a label, so a dashboard is not read for these)
# keys under which a name is not an entity at all: a Lovelace template library (the prototype dashboard defines a button-card template called ecco_intel_block)
NON_ENTITY_PARENT_KEYS = ("button_card_templates", "decluttering_templates")


def _intel_hits(node, path: str, dashboard: bool, non_entity: bool, hits: list) -> None:
    """Collect where a parsed YAML document defines or names an ecco_intel_ object id (see _foreign_definitions)."""
    if isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            here = f"{path}.{ks}" if path else ks
            if not non_entity and INTEL_OBJECT_RE.match(ks.strip().lower()):
                hits.append(f"{here} (a key named like an ecco_intel_ entity)")
            if isinstance(v, str):
                if ks in DEFINING_VALUE_KEYS and INTEL_OBJECT_RE.match(v.strip().lower()):
                    hits.append(f"{here}: {v.strip()[:60]} (an object id)")
                elif ks in NAMING_KEYS and not dashboard and INTEL_OBJECT_RE.match(_slug(v)):
                    hits.append(f"{here}: {v.strip()[:60]} (a name whose entity id is ecco_intel_...)")
            _intel_hits(v, here, dashboard, non_entity or ks in NON_ENTITY_PARENT_KEYS, hits)
    elif isinstance(node, list):
        for i, x in enumerate(node):
            _intel_hits(x, f"{path}[{i}]", dashboard, non_entity, hits)


def _registered_dashboard_files(root: Path) -> set[str]:
    """The repository files that the dashboard registration (lovelace: dashboards: <name>: filename:) points at: the deployed path `ecco/dashboards/x.yaml` is the repository file
    `home-assistant/dashboards/x.yaml`. A registration that points into home-assistant/packages/ is refused: a package cannot be a dashboard."""
    out: set[str] = set()
    reg = root / PACKAGE_DASHBOARD_REL
    if not reg.is_file():
        return out
    doc = _yaml(root, PACKAGE_DASHBOARD_REL)
    dashboards = (doc.get("lovelace") or {}).get("dashboards") if isinstance(doc, dict) and isinstance(doc.get("lovelace"), dict) else None
    for entry in (dashboards.values() if isinstance(dashboards, dict) else []):
        name = entry.get("filename") if isinstance(entry, dict) else None
        if not isinstance(name, str):
            continue
        norm = name.replace("\\", "/").lstrip("/")
        if not norm.startswith("ecco/"):
            continue
        rel = HA_DIR_REL + "/" + norm[len("ecco/"):]
        if ".." in rel.split("/"):
            raise UniverseError(f"{PACKAGE_DASHBOARD_REL}: the dashboard file name {name!r} leaves the repository")
        if rel.startswith(PACKAGES_DIR_REL):
            raise UniverseError(f"{PACKAGE_DASHBOARD_REL}: the dashboard registration points at {rel}, which is a package file: a package cannot be a dashboard (dashboards live under {DASHBOARD_DIR_REL})")
        out.add(rel)
    return out


def _foreign_definitions(root: Path) -> tuple[int, list[str]]:
    """Refuse (UniverseError) any YAML file under home-assistant/ OTHER than the three modelled package files that defines or names an `ecco_intel_` data point: a key
    (a helper, a legacy template sensor, a customize entry), a `unique_id`, `object_id` or `default_entity_id`, or, in a package, a `name` or `alias` whose slug is one.
    A reference to an entity (an `entity_id:` value, a template, a dashboard card) is not a definition and passes. Returns (files read, files parsed) for the tests.
    What it cannot see: a name built by a template or spelled with YAML escapes (a text search cannot read those)."""
    base = root / HA_DIR_REL
    if not base.is_dir():
        return 0, []
    modelled = set(PACKAGE_FILES)
    dashboards = set(PROTOTYPE_DASHBOARD_RELS) | _registered_dashboard_files(root)
    scanned = 0
    parsed: list[str] = []
    problems: list[str] = []
    for f in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in (".yaml", ".yml")):
        rel = f.relative_to(root).as_posix()
        if rel in modelled:
            continue
        scanned += 1
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise UniverseError(f"cannot read {rel}: {exc}") from None
        if rel.startswith(PACKAGES_DIR_REL) and VIEWS_KEY_RE.search(text):
            raise UniverseError(f"{rel}: a package file carries a top-level `views:` key, which only a dashboard has: a dashboard lives under {DASHBOARD_DIR_REL}, and what a file holds does not make it one")
        if not INTEL_MENTION_RE.search(text):
            continue
        try:
            docs = list(yaml.load_all(text, Loader=_Loader))
        except yaml.YAMLError as exc:
            raise UniverseError(f"{rel} spells ecco_intel but does not parse as YAML, so the tool cannot tell whether it defines a data point: {exc}") from None
        parsed.append(rel)
        dashboard = rel.startswith(DASHBOARD_DIR_REL) or rel in dashboards   # by location (review round 6), never by a `views` key
        if rel.startswith(PACKAGES_DIR_REL) and any(isinstance(d, dict) and "views" in d for d in docs):
            raise UniverseError(f"{rel}: a package file carries a top-level `views` key, which only a dashboard has: a dashboard lives under {DASHBOARD_DIR_REL}")
        hits: list[str] = []
        for d in docs:
            _intel_hits(d, "", dashboard, False, hits)
        problems.extend(f"{rel}: {h}" for h in hits)
    if problems:
        shown = "; ".join(problems[:8]) + (f"; and {len(problems) - 8} more" if len(problems) > 8 else "")
        raise UniverseError(f"home-assistant YAML other than the three ECCO Intelligence package files {list(PACKAGE_FILES)} defines or names an ecco_intel_ data point "
                            f"that tools/geek_mode_coverage.py does not read: {shown}. Model it (add its file to PACKAGE_FILES and read it in _package_entities) and catalogue it, or, "
                            f"if it is not a Home Assistant entity, add its parent key to NON_ENTITY_PARENT_KEYS")
    return scanned, parsed


def _package_entities(root: Path) -> tuple[list, list]:
    """(entities defined by the presentation package, entities defined by the prefs package) as [(domain, object id, spec dict, name key)].

    Fail closed: every top-level key and every kind of template entity of the three package files is either modelled here or refused with a
    UniverseError (see PACKAGE_*_KEYS); an entity id that two definitions produce is refused too."""
    _package_listing(root)
    pkg = _package_doc(root, PACKAGE_MAIN_REL, PACKAGE_MAIN_KEYS)
    prefs = _package_doc(root, PACKAGE_PREFS_REL, PACKAGE_PREFS_KEYS)
    _package_doc(root, PACKAGE_DASHBOARD_REL, PACKAGE_DASHBOARD_KEYS)
    seen: set[str] = set()

    def spec_of(rel: str, what: str, spec) -> dict:
        if spec is None:
            return {}
        if not isinstance(spec, dict):
            raise UniverseError(f"{rel}: {what} is not a mapping")
        return dict(spec)

    def add(bucket: list, rel: str, domain: str, obj, spec: dict, name_key: str) -> None:
        if not isinstance(obj, str) or not obj:
            raise UniverseError(f"{rel}: a {domain} entity has no usable name")
        eid = f"{domain}.{obj}"
        if eid in seen:
            raise UniverseError(f"{rel}: {eid} is defined more than once")
        seen.add(eid)
        bucket.append((domain, obj, spec, name_key))

    main: list = []
    ib = pkg.get("input_boolean")
    if ib is not None and not isinstance(ib, dict):
        raise UniverseError(f"{PACKAGE_MAIN_REL}: input_boolean is not a mapping of helpers")
    for key, spec in (ib or {}).items():
        add(main, PACKAGE_MAIN_REL, "input_boolean", key, spec_of(PACKAGE_MAIN_REL, f"input_boolean.{key}", spec), "name")
    blocks = pkg.get("template")
    if blocks is not None and not isinstance(blocks, list):
        raise UniverseError(f"{PACKAGE_MAIN_REL}: template is not a list of blocks")
    for block in blocks or []:
        if not isinstance(block, dict):
            raise UniverseError(f"{PACKAGE_MAIN_REL}: a template block is not a mapping")
        extra = sorted(str(k) for k in block if k not in TEMPLATE_BLOCK_KEYS)
        if extra:
            raise UniverseError(f"{PACKAGE_MAIN_REL}: the template block key(s) {extra} define entities (sensor, number, select, button, image, weather, a "
                                f"trigger-based block ...) that tools/geek_mode_coverage.py does not model (it models {list(TEMPLATE_BLOCK_KEYS)})")
        bs = block.get("binary_sensor")
        if bs is not None and not isinstance(bs, list):
            raise UniverseError(f"{PACKAGE_MAIN_REL}: template binary_sensor is not a list")
        for spec in bs or []:
            spec = spec_of(PACKAGE_MAIN_REL, "a template binary_sensor", spec)
            if not isinstance(spec.get("name"), str) or not _slug(spec["name"]):
                raise UniverseError(f"{PACKAGE_MAIN_REL}: a template binary_sensor has no usable name")
            add(main, PACKAGE_MAIN_REL, "binary_sensor", _slug(spec["name"]), spec, "name")
    autos = pkg.get("automation")
    if autos is not None and not isinstance(autos, list):
        raise UniverseError(f"{PACKAGE_MAIN_REL}: automation is not a list")
    for spec in autos or []:
        spec = spec_of(PACKAGE_MAIN_REL, "an automation", spec)
        if not isinstance(spec.get("alias"), str) or not _slug(spec["alias"]):
            raise UniverseError(f"{PACKAGE_MAIN_REL}: an automation has no usable alias")
        add(main, PACKAGE_MAIN_REL, "automation", _slug(spec["alias"]), spec, "alias")
    pre: list = []
    inum = prefs.get("input_number")
    if inum is not None and not isinstance(inum, dict):
        raise UniverseError(f"{PACKAGE_PREFS_REL}: input_number is not a mapping of helpers")
    for key, spec in (inum or {}).items():
        add(pre, PACKAGE_PREFS_REL, "input_number", key, spec_of(PACKAGE_PREFS_REL, f"input_number.{key}", spec), "name")
    return main, pre


def _card_reads(root: Path) -> dict:
    src = _read(root, "frontend/ecco-intelligence-card/ecco-intelligence-card.js")

    def block(name: str) -> str:
        m = re.search(rf"export const {name} = Object\.freeze\((.*?)\);\n", src, re.S)
        if not m:
            raise UniverseError(f"the Production card no longer declares {name}")
        return m.group(1)

    attrs = re.findall(r"'([a-z_0-9]+)'", block("ATTRIBUTES_READ"))
    blocks: dict[str, list[str]] = {}
    for name, body in re.findall(r"(\w+): Object\.freeze\(\[(.*?)\]\)", block("BLOCK_KEYS_READ"), re.S):
        blocks[name] = re.findall(r"'([a-z_0-9]+)'", body)
    labels = re.findall(r"'(I-D\d)'\s*:", block("DECISION_TITLES"))
    advice_keys = sorted(set(re.findall(r"\.advice\.([a-z_0-9]+)", src)))
    ents = re.findall(r"^\s+(\w+): '((?:sensor|binary_sensor|input_boolean)\.[a-z_0-9]+)',?$", block("DEFAULT_ENTITIES"), re.M)
    return {"attributes": sorted(set(attrs)), "blocks": {k: sorted(v) for k, v in sorted(blocks.items())},
            "decision_labels": labels, "advice_keys": advice_keys, "entities": sorted(e for _k, e in ents)}


def _dashboard_entities(root: Path) -> list[str]:
    doc = _yaml(root, "home-assistant/dashboards/ecco_intelligence.yaml") or {}
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "entity" and isinstance(v, str):
                    found.add(v)
                elif k == "entities":
                    if isinstance(v, dict):
                        found.update(x for x in v.values() if isinstance(x, str) and ENTITY_ID_RE.match(x))
                    elif isinstance(v, list):
                        for row in v:
                            if isinstance(row, str) and ENTITY_ID_RE.match(row):
                                found.add(row)
                            else:
                                walk(row)
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(doc)
    return sorted(found)


def _advice_keys(root: Path, ac) -> dict:
    """{entity key: {advice key: tag}} for the OK shape of each item and forecast, from the source of the advisors and the cycle."""
    out: dict[str, dict[str, str]] = {}
    sources = {"charge_target": "intelligence/charge_target.py", "overnight_demand": "intelligence/overnight.py",
               "export_event": "intelligence/events.py", "dump_to_grid": "intelligence/dump_advice.py"}
    if set(sources) != set(ac.ADVICE_ITEMS):
        raise UniverseError(f"the advice items are {ac.ADVICE_ITEMS} but tools/geek_mode_coverage.py knows {tuple(sources)}")
    for key, rel in sources.items():
        keys = dict_literal_keys(_tree(root, rel), "rec", rel)
        out[key] = {k: f"{rel}: the recommendation dict" for k in sorted(keys)}
    cyc = "intelligence/shadow_cycle.py"
    tree = _tree(root, cyc)
    day: list[str] | None = None
    for v in _assigned(tree, "summ"):
        if isinstance(v, ast.DictComp):
            for g in v.generators:
                for cond in g.ifs:
                    if isinstance(cond, ast.Compare) and isinstance(cond.ops[0], ast.In) and cond.comparators:
                        s = _strs(cond.comparators[0])
                        if s:
                            day = s
    if not day:
        raise UniverseError(f"{cyc}: the predicted_day_load summary key list was not found")
    out["predicted_day_load"] = {k: f"{cyc}: the day-load summary keys" for k in sorted(day)}
    out["pv_tomorrow"] = {k: "advisory_contract.PV_TOMORROW_SUMMARY_KEYS" for k in sorted(ac.PV_TOMORROW_SUMMARY_KEYS)}
    soc: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ForecastView" and node.args \
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "mk":
            for a in node.args:
                k = _str_keys(a)
                if k:
                    soc |= set(k)
    if not soc:
        raise UniverseError(f"{cyc}: the predicted_morning_soc summary dict was not found")
    out["predicted_morning_soc"] = {k: f"{cyc}: the morning-SOC summary dict" for k in sorted(soc)}
    if set(out) != set(ac.ADVICE_ITEMS) | set(ac.FORECAST_ITEMS):
        raise UniverseError("an advice item or forecast has no advice shape rule")
    return out


def _non_ok_advice_keys(root: Path) -> set[str]:
    """The keys of the advice attribute of an item that is not OK (`_view_advice`'s second return)."""
    tree = _tree(root, "intelligence/advisory_contract.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_view_advice":
            for r in [n for n in ast.walk(node) if isinstance(n, ast.Return)]:
                k = _str_keys(r.value) if r.value is not None else None
                if k:
                    return set(k)
    raise UniverseError("advisory_contract._view_advice has no dict-literal return (the non-OK advice shape moved)")


def build_universe(root: Path | None = None) -> Universe:
    root = (root or REPO).resolve()
    ac, sd, dp = load_contract(root)
    findings: list[str] = []

    # ---- (1) the contract: entities, attribute lists, the payloads the contract builders produce -------------------------------
    gen = _load_module(root, "intelligence/tests/_gen_contract_fixtures.py", "_geek_contract_fixture_builders")
    payload_attrs: dict[str, set[str]] = {}
    payload_nested: dict[tuple[str, str], set[str]] = {}
    payload_unit: dict[str, str] = {}
    for name in gen.NAMES:
        for eid, (_state, rec, unrec) in ac.to_entity_payloads(gen.BUILDERS[name]()).items():
            payload_attrs.setdefault(eid, set()).update(rec, unrec)
            if isinstance(rec.get("unit"), str):
                payload_unit[eid] = rec["unit"]
            for k, v in {**rec, **unrec}.items():
                if isinstance(v, dict):
                    payload_nested.setdefault((eid, k), set()).update(v.keys())
    kinds = {"status": "status", "accuracy": "accuracy", "data_quality": "data_quality", "fresh": "fresh",
             "paused": "pause_helper", "watchdog_fresh": "watchdog"}
    kinds.update({k: "item" for k in ac.ADVICE_ITEMS})
    kinds.update({k: "forecast" for k in ac.FORECAST_ITEMS})
    if set(kinds) != set(ac.ENTITY_IDS):
        raise UniverseError(f"ENTITY_IDS holds {sorted(set(ac.ENTITY_IDS) - set(kinds))} that this tool does not classify")
    declared_lists = {
        "status": ac.STATUS_RECORDED + ac.STATUS_UNRECORDED, "item": ac.ITEM_RECORDED + ac.ITEM_UNRECORDED,
        "forecast": ac.FORECAST_RECORDED + ac.FORECAST_UNRECORDED, "accuracy": ac.DIAG_RECORDED, "data_quality": ac.DIAG_RECORDED,
        "fresh": ac.FRESH_RECORDED}
    ha_attrs = _integration_ha_attrs(root, tuple(ac.INTEGRATION_ENTITY_KEYS))
    ents: dict[str, Ent] = {}
    for key, eid in ac.ENTITY_IDS.items():
        kind = kinds[key]
        origin = "package" if key in ac.PACKAGE_ENTITY_KEYS else "integration"
        ent = Ent(f"intel.{key}", key, eid, origin, kind, unit=payload_unit.get(eid))
        if origin == "integration":
            listed = set(declared_lists[kind])
            built = payload_attrs.get(eid, set())
            if listed != built:
                raise UniverseError(f"{eid}: the contract attribute list and the payload the contract builder produces disagree "
                                    f"(listed only: {sorted(listed - built)}; built only: {sorted(built - listed)})")
            list_name = {"status": "STATUS_RECORDED/UNRECORDED", "item": "ITEM_RECORDED/UNRECORDED",
                         "forecast": "FORECAST_RECORDED/UNRECORDED", "accuracy": "DIAG_RECORDED", "data_quality": "DIAG_RECORDED",
                         "fresh": "FRESH_RECORDED"}[kind]
            for a in sorted(listed):
                _add(ent, a, f"contract {list_name}")
            for a, tag in sorted(ha_attrs[key].items()):
                _add(ent, a, f"Home Assistant standard ({tag})")
        ents[key] = ent

    # ---- (2) nested keys -------------------------------------------------------------------------------------------------------
    st = ents["status"]
    for name, keys in ac.BLOCK_KEYS.items():
        for k in sorted(keys):
            _add(st, f"{name}.{k}", "contract BLOCK_KEYS")
    for name in ("decisions", "last_good", "accuracy"):
        for k in sorted(payload_nested.get((ac.ENTITY_IDS["status"], name), ())):
            _add(st, f"{name}.{k}", "contract entity payload (to_entity_payloads)")
    labels = [sd.display_label(d) for d in sd.DECISION_IDS]
    got = {k for k in payload_nested.get((ac.ENTITY_IDS["status"], "decisions"), ())}
    if got != set(labels):
        raise UniverseError(f"the decisions attribute carries {sorted(got)} but the decision ids give {labels}")
    acc_built = payload_nested.get((ac.ENTITY_IDS["status"], "accuracy"), set())
    if not acc_built <= set(ac.BLOCK_KEYS["accuracy"]):
        raise UniverseError("the accuracy block carries keys that BLOCK_KEYS does not declare")
    for g in ("decisions.", "last_good.", "accuracy."):
        if not any(p.startswith(g) for p in st.attrs):
            raise UniverseError(f"no nested keys were found for the status attribute {g[:-1]}")
    advice = _advice_keys(root, ac)
    non_ok = _non_ok_advice_keys(root)
    engine_keys = dict_literal_keys(_tree(root, "intelligence/shadow_cycle.py"), "engine_cmp", "intelligence/shadow_cycle.py")
    for key, keys in advice.items():
        ent = ents[key]
        for k, tag in keys.items():
            _add(ent, f"advice.{k}", tag, "ok")
        for k in sorted(non_ok):
            _add(ent, f"advice.{k}", "advisory_contract._view_advice (the shape of an item that is not OK)", "non_ok")
        eng = payload_nested.get((ent.entity_id, "engine_comparison"))
        if eng:
            for k in sorted(engine_keys):
                _add(ent, f"engine_comparison.{k}", "intelligence/shadow_cycle.py: the engine comparison dict")
    if not payload_nested.get((ac.ENTITY_IDS["charge_target"], "engine_comparison")):
        raise UniverseError("charge_target no longer carries an engine_comparison dict in the contract fixtures")

    # ---- (3) the presentation packages -----------------------------------------------------------------------------------------
    main, pre = _package_entities(root)
    wanted = {"input_boolean": ac.ENTITY_IDS["paused"], "binary_sensor": ac.ENTITY_IDS["watchdog_fresh"]}
    seen_pkg: set[str] = set()
    for domain, obj, spec, name_key in main + pre:
        eid = f"{domain}.{obj}"
        if domain == "automation":
            uid = str(spec.get("id", ""))
            if not uid.startswith(DISCOVER_NAME_PREFIX):
                raise UniverseError(f"automation {eid} has an id that does not start with {DISCOVER_NAME_PREFIX}")
            ent = Ent(f"intel.automation.{uid[len(DISCOVER_NAME_PREFIX):]}", uid, eid, "package", "automation")
        elif domain == "input_number":
            ent = Ent(f"intel.pref.{obj.replace('ecco_', '', 1)}", obj, eid, "package", "reserve_helper")
        else:
            key = next((k for k, v in ac.ENTITY_IDS.items() if v == eid), None)
            if key is None:
                raise UniverseError(f"the package defines {eid}, which is not a contract entity")
            ent = ents[key]
            seen_pkg.add(eid)
        if isinstance(spec.get("unit_of_measurement"), str):
            ent.unit = spec["unit_of_measurement"]
        _add(ent, "friendly_name", f"package YAML: the {name_key}")
        for a in HA_DOMAIN_ATTRIBUTES.get(domain, ()):
            _add(ent, a, f"Home Assistant {domain} standard")
        if domain != "automation":
            for a in YAML_HELPER_ATTRIBUTES:
                if a in spec:
                    _add(ent, a, "package YAML: the helper definition")
        if domain == "binary_sensor" and "icon" in spec:
            _add(ent, "icon", "package YAML: the helper definition")
        if domain == "automation":
            ents[ent.key] = ent
        elif domain == "input_number":
            ents[ent.key] = ent
    missing = sorted(set(wanted.values()) - seen_pkg)
    if missing:
        raise UniverseError(f"the contract's package entities {missing} are not defined by home-assistant/packages/ecco_intelligence.yaml")

    # ---- (4) timing, redaction, diagnostics, names, the dashboard, the card ---------------------------------------------------------
    const = _load_module(root, "custom_components/ecco_intelligence/const.py", "_geek_ecco_intel_const")
    stale_after = float(dp.PROPOSED_ADVICE_VALIDITY_S + const.TICK_S + const.PROPOSED_TIME_BUDGET_S + 2 * 60.0)
    pkg_text = _read(root, "home-assistant/packages/ecco_intelligence.yaml")
    if not re.search(rf"\(t - gt\) <= {int(stale_after)}\b", pkg_text):
        raise UniverseError(f"the watchdog template no longer uses the {int(stale_after)} s maximum age derived from the integration "
                            f"constants (validity + tick + time budget + 2 x 60 s)")
    diag_tree = _tree(root, "custom_components/ecco_intelligence/diagnostics.py")
    redact = next((sorted(_strs(v) or []) for v in _assigned(diag_tree, "TO_REDACT")), [])
    if not redact:
        raise UniverseError("custom_components/ecco_intelligence/diagnostics.py has no TO_REDACT set")
    coord = _tree(root, "custom_components/ecco_intelligence/coordinator.py")
    sections: list[str] | None = None
    for node in ast.walk(coord):
        if isinstance(node, ast.FunctionDef) and node.name == "diagnostics":
            for r in [n for n in ast.walk(node) if isinstance(n, ast.Return)]:
                k = _str_keys(r.value) if r.value is not None else None
                if k:
                    sections = k
    if not sections:
        raise UniverseError("coordinator.diagnostics has no dict-literal return")
    names_tree = _tree(root, "custom_components/ecco_intelligence/entity_base.py")
    names = next((ast.literal_eval(v) for v in _assigned(names_tree, "NAMES")), None)
    if not isinstance(names, dict):
        raise UniverseError("entity_base.NAMES was not found")
    for key in ac.INTEGRATION_ENTITY_KEYS:
        if key not in names:
            raise UniverseError(f"entity_base.NAMES has no name for {key}")
    envelope_fields = [f.name for f in dataclasses.fields(ac.AdvisoryEnvelope)]
    version_fields = [f.name for f in dataclasses.fields(ac.Versions)]
    published = {p for e in ents.values() for p in e.attrs if "." not in p} | {"items", "forecasts", "versions"}
    unpublished = sorted(f for f in envelope_fields if f not in published)
    for v in version_fields:
        if v not in st.attrs:
            findings.append(f"the contract's Versions field {v} is not a status attribute")
    dash = _dashboard_entities(root)
    card = _card_reads(root)
    for a in card["attributes"]:
        if not any(a in {p.split(".")[0] for p in e.attrs} for e in ents.values()):
            findings.append(f"the Production card reads the attribute {a}, which no declared source carries")
    return Universe(
        entities=sorted(ents.values(), key=lambda e: e.ident), findings=findings, contract_version=ac.CONTRACT_VERSION,
        expected_update_s=float(const.TICK_S), stale_after_s=stale_after, redact_keys=redact, diag_sections=sections,
        envelope_unpublished=unpublished, site_reading_keys=sorted(ac.SITE_READING_KEYS), card_reads=card,
        dashboard_entities=dash, status_values=list(ac.SystemStatus.ALL), dq_values=list(ac.DataQuality.ALL),
        decision_labels=labels, decision_titles={sd.display_label(d): sd.DECISION_TITLES[d] for d in sd.DECISION_IDS})


def universe_friendly_names(root: Path | None = None) -> dict:
    """{entity id: the friendly name Home Assistant gives it}, from the integration's NAMES and the packages' names."""
    root = (root or REPO).resolve()
    ac, _sd, _dp = load_contract(root)
    names_tree = _tree(root, "custom_components/ecco_intelligence/entity_base.py")
    names = next(ast.literal_eval(v) for v in _assigned(names_tree, "NAMES"))
    out = {ac.ENTITY_IDS[k]: v for k, v in names.items()}
    main, pre = _package_entities(root)
    for domain, obj, spec, name_key in main + pre:
        out[f"{domain}.{obj}"] = spec[name_key]
    return out


# ---------------------------------------------------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------------------------------------------------

def unit_for(path: str, entity_unit: str | None, overrides: dict) -> str | None:
    if path in overrides:
        return overrides[path]
    leaf = path.rsplit(".", 1)[-1]
    if leaf in overrides:
        return overrides[leaf]
    if leaf in ("p10", "p50", "p90"):
        return entity_unit
    for suffix, unit in (("_kw_avg", "kW"), ("_kwh", "kWh"), ("_pct", "%"), ("_gbp", "GBP"), ("_s", "s"), ("_w", "W")):
        if leaf.endswith(suffix):
            return unit
    return None


def _lookup(T, ent: Ent, path: str, used: set):
    for layer, table in (("entity", T.ENTITY_ATTRS.get(ent.ident, {})), ("kind", T.KIND_ATTRS.get(ent.kind, {})), ("common", T.COMMON_ATTRS)):
        if path in table:
            used.add((layer, ent.ident if layer == "entity" else ent.kind if layer == "kind" else "", path))
            return table[path]
    return None


def build_catalogue(u: Universe, T) -> dict:
    """The catalogue `ecco-geek-catalogue/1`. Raises CoverageError when the texts and the universe disagree."""
    problems: list[str] = []
    used: set = set()
    groups = [dict(g) for g in T.GROUPS]
    ids = {e.ident for e in u.entities}
    for ident in sorted(ids - set(T.SOURCES)):
        problems.append(f"UNCATALOGUED source {ident}: no text in tools/geek_mode_texts_intelligence.py SOURCES")
    for ident in sorted(set(T.SOURCES) - ids):
        problems.append(f"ORPHAN text for source {ident}: no such source in the code")
    sources = []
    for ent in sorted(u.entities, key=lambda e: e.ident):
        meta = T.SOURCES.get(ent.ident)
        if meta is None:
            continue
        unit = ent.unit
        attrs = []
        for path in sorted(ent.attrs):
            if ent.kind == "status" and path.startswith("decisions.") and path.split(".", 1)[1] in u.decision_titles:
                label = path.split(".", 1)[1]
                attrs.append({"name": path, "description": T.DECISION_ATTR[1].format(label=label, title=u.decision_titles[label]),
                              "unit": None, "priority": T.DECISION_ATTR[0]})
                continue
            hit = _lookup(T, ent, path, used)
            if hit is None:
                problems.append(f"UNCATALOGUED attribute {ent.entity_id} {path}: no text (tags: {'; '.join(ent.attrs[path]['tags'])})")
                continue
            prio, text = hit
            attrs.append({"name": path, "description": text, "unit": unit_for(path, unit, T.ATTR_UNITS), "priority": prio})
        timed = ent.origin == "integration"
        sources.append({
            "id": ent.ident, "entity_id": ent.entity_id, "group": meta["group"], "title": meta["title"],
            "description": meta["description"], "priority": meta["priority"], "unit": unit,
            "expected_update_s": u.expected_update_s if timed else None,
            "stale_after_s": u.stale_after_s if timed else None, "origin": ent.origin, "attributes": attrs})
    for layer, table in (("entity", T.ENTITY_ATTRS), ("kind", T.KIND_ATTRS)):
        for owner, rows in table.items():
            for path in rows:
                if (layer, owner, path) not in used:
                    problems.append(f"ORPHAN text ({layer} layer, {owner}) for attribute {path}: no source carries it")
    for path in T.COMMON_ATTRS:
        if ("common", "", path) not in used:
            problems.append(f"ORPHAN text (common layer) for attribute {path}: no source carries it")
    # alerts, derived from the contract's statuses
    alerts = []
    status_ids = set(T.STATUS_ALERTS) | set(T.NO_ALERT_STATUSES)
    if set(T.STATUS_ALERTS) & set(T.NO_ALERT_STATUSES) or status_ids != set(u.status_values):
        problems.append(f"the system statuses are {sorted(u.status_values)} but the alert texts cover {sorted(status_ids)}")
    dq_ids = set(T.DQ_ALERTS) | set(T.NO_ALERT_DQ)
    if set(T.DQ_ALERTS) & set(T.NO_ALERT_DQ) or dq_ids != set(u.dq_values):
        problems.append(f"the data-quality states are {sorted(u.dq_values)} but the alert texts cover {sorted(dq_ids)}")
    ent_of = {e.key: e.entity_id for e in u.entities}

    def resolve_when(when: dict) -> dict:
        """The texts file carries two placeholders (the contract version and the list of statuses); the values come from the code."""
        out = json.loads(json.dumps(when))
        if out.get("state_outside") == ["@statuses"]:
            out["state_outside"] = sorted(u.status_values)
        if out.get("not_in") == ["@contract_version"]:
            out["not_in"] = [u.contract_version]
        return out

    for status, (sev, text, action) in sorted(T.STATUS_ALERTS.items()):
        alerts.append({"id": f"status_{status.lower()}", "severity": sev, "entity_id": ent_of["status"],
                       "when": {"state_in": [status]}, "text": text, "action": action})
    for dq, (sev, text, action) in sorted(T.DQ_ALERTS.items()):
        alerts.append({"id": f"data_quality_{dq.lower()}", "severity": sev, "entity_id": ent_of["data_quality"],
                       "when": {"state_in": [dq]}, "text": text, "action": action})
    for row in T.OTHER_ALERTS:
        if row["entity"] not in ent_of:
            problems.append(f"alert {row['id']} names the unknown entity key {row['entity']!r}")
            continue
        alerts.append({"id": row["id"], "severity": row["severity"], "entity_id": ent_of[row["entity"]], "when": resolve_when(row["when"]),
                       "text": row["text"], "action": row["action"]})
    sev_rank = {s: i for i, s in enumerate(SEVERITIES)}
    alerts.sort(key=lambda a: (sev_rank[a["severity"]], a["id"]))
    # exceptions: what is not a Home Assistant state, computed where the code can say
    exceptions = build_exceptions(u, T, problems)
    if problems:
        raise CoverageError("\n".join(problems))
    redaction = {"extra_key_patterns": sorted(set(T.EXTRA_REDACTION_KEYS) | {r.lower() for r in u.redact_keys})}
    discover = {"entity_prefixes": [f"{d}.{DISCOVER_NAME_PREFIX}" for d in DISCOVER_DOMAINS], "group": "discovered", "exclude_entity_ids": []}
    group_order = {g["id"]: g["order"] for g in groups}
    sources.sort(key=lambda s: (group_order[s["group"]], s["id"]))
    return {"schema": SCHEMA, "view_id": VIEW_ID, "title": T.TITLE, "contract": u.contract_version, "groups": groups,
            "sources": sources, "discover": discover, "alerts": alerts, "exceptions": exceptions, "redaction": redaction}


def diag_covered(u: Universe, T, problems: list | None = None) -> dict:
    """{diagnostics section: [status attributes that carry the same information]} for the sections the texts declare covered, each
    claim checked against the status entity's real attributes."""
    status_attrs = set(u.by_ident()["intel.status"].attrs)
    out: dict[str, list[str]] = {}
    for key, attrs in sorted(T.DIAG_COVERED.items()):
        if key not in u.diag_sections:
            if problems is not None:
                problems.append(f"ORPHAN text for covered diagnostics section {key}: the download no longer has it")
            continue
        missing = [a for a in attrs if a not in status_attrs]
        if missing:
            if problems is not None:
                problems.append(f"diagnostics section {key} is declared covered by status attributes that do not exist: {missing}")
            continue
        out[key] = list(attrs)
    return out


def build_exceptions(u: Universe, T, problems: list) -> list:
    out = []
    ids: set[str] = set()

    def add(ident: str, what: str, reason: str, note: str) -> None:
        if ident in ids:
            problems.append(f"duplicate exception id {ident}")
        ids.add(ident)
        out.append({"id": ident, "what": what, "reason": reason, "note": note})

    covered = diag_covered(u, T, problems)
    for key in u.diag_sections:
        meta = T.DIAG_SECTIONS.get(key)
        if meta is None:
            problems.append(f"UNCATALOGUED diagnostics section {key}: no text in DIAG_SECTIONS")
            continue
        if key in covered:
            continue                      # the same information is a status attribute with a row: not an exception
        reason = "privacy" if key in u.redact_keys else "not_exposed_in_states"
        partial = T.DIAG_PARTIAL.get(key)
        note = meta + (f" {partial}" if partial else "")
        if reason == "not_exposed_in_states":
            note += " Not in any state or attribute: showing it would need a new read-only diagnostic entity (a contract change request)."
        else:
            note += " The integration's own diagnostics download redacts it as a site value, so Geek Mode withholds it as well."
        add(f"diag.{key}", f"Diagnostics download section '{key}'", reason, note)
    for key in sorted(set(T.DIAG_SECTIONS) - set(u.diag_sections)):
        problems.append(f"ORPHAN text for diagnostics section {key}: the download no longer has it")
    attr_names = {p for e in u.entities for p in e.attrs}
    for key in sorted(set(u.redact_keys) - set(u.diag_sections) - attr_names):
        add(f"redacted.{key}", f"Redacted diagnostics field '{key}'", "privacy",
            "The integration's own diagnostics download redacts this site value; Geek Mode never shows it.")
    for f in u.envelope_unpublished:
        meta = T.ENVELOPE_UNPUBLISHED.get(f)
        if meta is None:
            problems.append(f"the contract's AdvisoryEnvelope field {f} is published by no entity and has no exception text")
            continue
        add(f"envelope.{f}", f"Contract field '{f}' (an internal result of one cycle)", "not_exposed_in_states", meta)
    for f in sorted(set(T.ENVELOPE_UNPUBLISHED) - set(u.envelope_unpublished)):
        problems.append(f"ORPHAN text for the unpublished envelope field {f}: an entity publishes it now")
    add("site_readings", f"The {len(u.site_reading_keys)} site readings one cycle consumes (battery state, capacity, tariff tables, forecasts, ...)",
        "not_exposed_in_states",
        "They are the owner's other entities, read through the site file's mapping. Intelligence publishes only their names and ages "
        "(the status attribute input_ages), never their values. Their values belong to those entities' own tabs.")
    for ident, (what, reason, note) in sorted(T.OTHER_EXCEPTIONS.items()):
        add(ident, what, reason, note)
    out.sort(key=lambda e: e["id"])
    return out


# ---------------------------------------------------------------------------------------------------------------------
# validation (the agreed schema ecco-geek-catalogue/1; the card has its own validator)
# ---------------------------------------------------------------------------------------------------------------------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _keys(obj, required: set, optional: set, where: str, errs: list, strict: bool) -> bool:
    if not isinstance(obj, dict):
        errs.append(f"{where}: must be an object")
        return False
    for k in sorted(required - set(obj)):
        errs.append(f"{where}: missing key {k}")
    if strict:
        for k in sorted(set(obj) - required - optional):
            errs.append(f"{where}: unknown key {k}")
    return True


def validate_catalogue(cat, strict: bool = True) -> list[str]:
    """Every problem of a catalogue against ecco-geek-catalogue/1 ([] when it is valid). Pure."""
    errs: list[str] = []
    if not _keys(cat, {"schema", "view_id", "title", "contract", "groups", "sources", "discover", "alerts", "exceptions", "redaction"},
                 set(), "catalogue", errs, strict):
        return errs
    if cat.get("schema") != SCHEMA:
        errs.append(f"catalogue.schema must be {SCHEMA}, got {cat.get('schema')!r}")
        return errs
    for k in ("view_id", "title", "contract"):
        if not isinstance(cat.get(k), str) or not cat.get(k):
            errs.append(f"catalogue.{k}: must be a non-empty text")
    group_ids: set = set()
    if not isinstance(cat.get("groups"), list):
        errs.append("catalogue.groups: must be a list")
    else:
        for i, g in enumerate(cat["groups"]):
            w = f"groups[{i}]"
            if _keys(g, {"id", "title", "order", "description"}, set(), w, errs, strict):
                if not isinstance(g.get("id"), str) or not SOURCE_ID_RE.match(g.get("id") or ""):
                    errs.append(f"{w}.id: must be a lower-case id")
                elif g["id"] in group_ids:
                    errs.append(f"{w}.id: duplicate {g['id']}")
                else:
                    group_ids.add(g["id"])
                if not isinstance(g.get("title"), str) or not g.get("title"):
                    errs.append(f"{w}.title: must be a non-empty text")
                if not isinstance(g.get("order"), int) or isinstance(g.get("order"), bool):
                    errs.append(f"{w}.order: must be an integer")
                if not isinstance(g.get("description"), str):
                    errs.append(f"{w}.description: must be a text")
    src_ids: set = set()
    entity_ids: set = set()
    if not isinstance(cat.get("sources"), list):
        errs.append("catalogue.sources: must be a list")
    else:
        for i, s in enumerate(cat["sources"]):
            w = f"sources[{i}]"
            if not _keys(s, {"id", "entity_id", "group", "title", "description", "priority", "unit", "expected_update_s",
                             "stale_after_s", "origin", "attributes"}, set(), w, errs, strict):
                continue
            sid = s.get("id")
            if not isinstance(sid, str) or not SOURCE_ID_RE.match(sid or ""):
                errs.append(f"{w}.id: must be a stable lower-case id")
            elif sid in src_ids:
                errs.append(f"{w}.id: duplicate {sid}")
            else:
                src_ids.add(sid)
            eid = s.get("entity_id")
            if not isinstance(eid, str) or not ENTITY_ID_RE.match(eid or ""):
                errs.append(f"{w}.entity_id: must be a Home Assistant entity id")
            elif eid in entity_ids:
                errs.append(f"{w}.entity_id: duplicate {eid}")
            else:
                entity_ids.add(eid)
            if s.get("group") not in group_ids:
                errs.append(f"{w}.group: {s.get('group')!r} is not a declared group")
            for k in ("title", "description"):
                if not isinstance(s.get(k), str) or not s.get(k).strip():
                    errs.append(f"{w}.{k}: must be a non-empty text")
            if s.get("priority") not in PRIORITIES:
                errs.append(f"{w}.priority: must be one of {PRIORITIES}")
            if s.get("origin") not in ORIGINS:
                errs.append(f"{w}.origin: must be one of {ORIGINS}")
            if s.get("unit") is not None and not isinstance(s.get("unit"), str):
                errs.append(f"{w}.unit: must be a text or null")
            for k in ("expected_update_s", "stale_after_s"):
                v = s.get(k)
                if v is not None and not (_is_num(v) and v > 0):
                    errs.append(f"{w}.{k}: must be a positive number or null")
            if _is_num(s.get("expected_update_s")) and _is_num(s.get("stale_after_s")) and s["stale_after_s"] < s["expected_update_s"]:
                errs.append(f"{w}.stale_after_s: must not be below expected_update_s")
            attrs = s.get("attributes")
            if not isinstance(attrs, list):
                errs.append(f"{w}.attributes: must be a list")
                continue
            names: set = set()
            for j, a in enumerate(attrs):
                aw = f"{w}.attributes[{j}]"
                if not _keys(a, {"name", "description", "unit", "priority"}, set(), aw, errs, strict):
                    continue
                n = a.get("name")
                if not isinstance(n, str) or not ATTR_NAME_RE.match(n or ""):
                    errs.append(f"{aw}.name: must be an attribute name, or one dotted path into the first nesting level")
                elif n in names:
                    errs.append(f"{aw}.name: duplicate {n}")
                else:
                    names.add(n)
                if not isinstance(a.get("description"), str) or not a.get("description").strip():
                    errs.append(f"{aw}.description: must be a non-empty text")
                if a.get("unit") is not None and not isinstance(a.get("unit"), str):
                    errs.append(f"{aw}.unit: must be a text or null")
                if a.get("priority") not in PRIORITIES:
                    errs.append(f"{aw}.priority: must be one of {PRIORITIES}")
            for n in sorted(names):
                if "." in n and n.split(".", 1)[0] not in names:
                    errs.append(f"{w}.attributes: the dotted path {n} has no declared parent attribute")
    d = cat.get("discover")
    if _keys(d, {"entity_prefixes", "group", "exclude_entity_ids"}, set(), "discover", errs, strict):
        pf = d.get("entity_prefixes")
        if not isinstance(pf, list) or not pf or not all(isinstance(p, str) and PREFIX_RE.match(p) for p in pf):
            errs.append("discover.entity_prefixes: a non-empty list of '<domain>.<name>_' prefixes")
        if d.get("group") not in group_ids:
            errs.append(f"discover.group: {d.get('group')!r} is not a declared group")
        ex = d.get("exclude_entity_ids")
        if not isinstance(ex, list) or not all(isinstance(x, str) and ENTITY_ID_RE.match(x) for x in ex):
            errs.append("discover.exclude_entity_ids: a list of entity ids")
    alert_ids: set = set()
    if not isinstance(cat.get("alerts"), list):
        errs.append("catalogue.alerts: must be a list")
    else:
        for i, a in enumerate(cat["alerts"]):
            w = f"alerts[{i}]"
            if not _keys(a, {"id", "severity", "entity_id", "when", "text", "action"}, set(), w, errs, strict):
                continue
            if not isinstance(a.get("id"), str) or not SOURCE_ID_RE.match(a.get("id") or ""):
                errs.append(f"{w}.id: must be a lower-case id")
            elif a["id"] in alert_ids:
                errs.append(f"{w}.id: duplicate {a['id']}")
            else:
                alert_ids.add(a["id"])
            if a.get("severity") not in SEVERITIES:
                errs.append(f"{w}.severity: must be one of {SEVERITIES}")
            if a.get("entity_id") not in entity_ids:
                errs.append(f"{w}.entity_id: {a.get('entity_id')!r} is not a catalogued entity")
            for k in ("text", "action"):
                if not isinstance(a.get(k), str) or not a.get(k).strip():
                    errs.append(f"{w}.{k}: must be a non-empty text")
            when = a.get("when")
            if not isinstance(when, dict):
                errs.append(f"{w}.when: must be an object")
            else:
                shape = tuple(sorted(when))
                if shape in (("state_in",), ("state_not_in",), ("state_outside",)):
                    v = when[shape[0]]
                    if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
                        errs.append(f"{w}.when.{shape[0]}: a non-empty list of texts")
                elif shape == ("unavailable",):
                    if when["unavailable"] is not True:
                        errs.append(f"{w}.when.unavailable: must be true")
                elif shape in (("attribute", "in"), ("attribute", "not_in")):
                    if not isinstance(when["attribute"], str) or not when["attribute"]:
                        errs.append(f"{w}.when.attribute: must be an attribute name")
                    listed = when[shape[1]]
                    if not isinstance(listed, list) or not listed or not all(isinstance(x, (str, bool, int, float)) for x in listed):
                        errs.append(f"{w}.when.{shape[1]}: a non-empty list of plain values")
                else:
                    errs.append(f"{w}.when: must be exactly one of {{state_in}}, {{state_not_in}}, {{state_outside}}, {{unavailable: true}}, "
                                f"{{attribute, in}}, {{attribute, not_in}}")
    exc_ids: set = set()
    if not isinstance(cat.get("exceptions"), list):
        errs.append("catalogue.exceptions: must be a list")
    else:
        for i, e in enumerate(cat["exceptions"]):
            w = f"exceptions[{i}]"
            if not _keys(e, {"id", "what", "reason", "note"}, set(), w, errs, strict):
                continue
            if not isinstance(e.get("id"), str) or not SOURCE_ID_RE.match(e.get("id") or ""):
                errs.append(f"{w}.id: must be a lower-case id")
            elif e["id"] in exc_ids:
                errs.append(f"{w}.id: duplicate {e['id']}")
            else:
                exc_ids.add(e["id"])
            if e.get("reason") not in EXCEPTION_REASONS:
                errs.append(f"{w}.reason: must be one of {EXCEPTION_REASONS}")
            for k in ("what", "note"):
                if not isinstance(e.get(k), str) or not e.get(k).strip():
                    errs.append(f"{w}.{k}: must be a non-empty text (every exception is justified)")
    r = cat.get("redaction")
    if _keys(r, {"extra_key_patterns"}, set(), "redaction", errs, strict):
        p = r.get("extra_key_patterns")
        if not isinstance(p, list):
            errs.append("redaction.extra_key_patterns: a list of plain lower-case key fragments (1 to 80 characters of a-z, 0-9, _)")
        else:
            for i, x in enumerate(p):
                if not (isinstance(x, str) and PATTERN_RE.fullmatch(x)):
                    errs.append(f"redaction.extra_key_patterns[{i}]: a plain lower-case key fragment of 1 to 80 characters of a-z, 0-9 and _ "
                                f"(the card matches it as a part of a key name, never as an expression)")
            if len(p) > PATTERN_MAX_COUNT:
                errs.append(f"redaction.extra_key_patterns: at most {PATTERN_MAX_COUNT} fragments (the card reads no more, so the rest would be ignored)")
    return errs


def coverage_problems(cat: dict, u: Universe) -> list[str]:
    """Every difference between a catalogue and the computed universe ([] when the catalogue covers it exactly). Pure: the
    same function the tests apply to the committed catalogue and to mutated ones."""
    out: list[str] = []
    cat_sources = {s.get("entity_id"): s for s in cat.get("sources", []) if isinstance(s, dict)}
    for ent in u.entities:
        s = cat_sources.get(ent.entity_id)
        if s is None:
            out.append(f"UNCOVERED source {ent.entity_id} ({ent.ident})")
            continue
        if s.get("id") != ent.ident:
            out.append(f"WRONG ID for {ent.entity_id}: catalogue {s.get('id')!r}, expected {ent.ident!r}")
        have = {a.get("name") for a in s.get("attributes", []) if isinstance(a, dict)}
        for p in sorted(set(ent.attrs) - have):
            out.append(f"UNCOVERED attribute {ent.entity_id} {p}")
        for p in sorted(have - set(ent.attrs)):
            out.append(f"UNAVAILABLE attribute {ent.entity_id} {p}: declared in the catalogue but no code produces it")
    known = {e.entity_id for e in u.entities}
    for eid in sorted(set(cat_sources) - known):
        out.append(f"UNAVAILABLE source {eid}: in the catalogue but not in the code")
    for a in cat.get("alerts", []):
        if isinstance(a, dict) and a.get("entity_id") not in cat_sources:
            out.append(f"alert {a.get('id')} names {a.get('entity_id')!r}, which is not a catalogued source")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# the live comparison
# ---------------------------------------------------------------------------------------------------------------------

def load_shape(path: Path) -> dict:
    try:
        shape = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UniverseError(f"cannot read the live shape listing {path}: {exc}") from None
    if not isinstance(shape, dict) or not isinstance(shape.get("ecco_intel"), list):
        raise UniverseError(f"{path}: not a live shape listing (no ecco_intel list)")
    return shape


def compare_live(u: Universe, shape: dict) -> dict:
    """The live comparison: entity and attribute statuses and the findings. `shape` holds names, types and sizes only."""
    needle = (shape.get("_provenance") or {}).get("object_id_contains", DISCOVER_NAME_PREFIX.rstrip("_"))
    live = {row["entity_id"]: row for row in shape["ecco_intel"]}
    declared = {e.entity_id: e for e in u.entities}
    ent_status: dict[str, str] = {}
    attr_status: dict[tuple[str, str], dict] = {}
    undeclared: list[dict] = []
    not_present: list[dict] = []
    not_checked: list[str] = []
    for eid, ent in declared.items():
        obj = eid.split(".", 1)[1]
        if eid in live:
            ent_status[eid] = "PRESENT_LIVE"
        elif needle not in obj:
            ent_status[eid] = "NOT_CHECKED_LIVE"
            not_checked.append(eid)
            continue
        else:
            ent_status[eid] = "NOT_PRESENT_LIVE"
            not_present.append({"entity_id": eid, "path": None, "why": "declared, but the live listing has no such entity"})
            continue
        row = live[eid]
        la = row.get("attributes") or {}
        live_paths: dict[str, dict] = {}
        for name, info in la.items():
            live_paths[name] = {"type": info.get("type"), "bytes": info.get("bytes")}
            for k in info.get("top_keys") or []:
                live_paths[f"{name}.{k}"] = {"type": None, "bytes": None}
        advice_live = set((la.get("advice") or {}).get("top_keys") or [])
        non_ok_live = bool(advice_live) and advice_live <= {"status", "blocker_codes"}
        for p, info in ent.attrs.items():
            if p in live_paths:
                attr_status[(eid, p)] = {"live": "PRESENT_LIVE", **live_paths[p]}
            else:
                why = "declared, absent from the live entity"
                parent = la.get(p.split(".")[0]) if "." in p else None
                if parent is not None and parent.get("type") == "null":
                    why = f"conditional: the live attribute {p.split('.')[0]} is empty (null), so its keys are absent"
                elif p.startswith("advice.") and info.get("shape") == "ok" and non_ok_live:
                    why = "conditional: the live item is not OK, so only the non-OK advice shape is present"
                elif p.startswith("advice.") and info.get("shape") == "non_ok" and advice_live and not non_ok_live:
                    why = "conditional: the live item is OK, so only the OK advice shape is present"
                attr_status[(eid, p)] = {"live": "NOT_PRESENT_LIVE", "type": None, "bytes": None, "why": why}
                not_present.append({"entity_id": eid, "path": p, "why": why})
        for p in sorted(set(live_paths) - set(ent.attrs)):
            undeclared.append({"entity_id": eid, "path": p, "why": "present live, declared by no code or package"})
    for eid in sorted(set(live) - set(declared)):
        undeclared.append({"entity_id": eid, "path": None, "why": "an entity present live that no contract, package or integration code declares"})
    return {"entities": ent_status, "attributes": attr_status, "undeclared": undeclared, "not_present_live": not_present,
            "not_checked_live": sorted(not_checked), "live_entities": len(live), "filter": needle}


# ---------------------------------------------------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fmt(obj, depth: int, limit: int) -> str:
    """JSON with one line per element down to `limit` levels of nesting and one line for everything below: a diff of a generated
    file then shows one changed attribute or row as one changed line. Plain JSON (Home Assistant's !include loads it as YAML)."""
    if depth >= limit or not isinstance(obj, (dict, list)) or not obj:
        return json.dumps(obj, ensure_ascii=True, separators=(", ", ": "), allow_nan=False)
    pad = " " * depth
    if isinstance(obj, dict):
        body = ",\n".join(f"{pad} {json.dumps(k, ensure_ascii=True)}: {_fmt(v, depth + 1, limit)}" for k, v in obj.items())
        return "{\n" + body + "\n" + pad + "}"
    return "[\n" + ",\n".join(f"{pad} {_fmt(v, depth + 1, limit)}" for v in obj) + "\n" + pad + "]"


def _json_bytes(obj, limit: int = 2) -> bytes:
    return (_fmt(obj, 0, limit) + "\n").encode("ascii")


def fixture_presence(out_root: Path) -> dict | None:
    """{(entity id, path): [fixture names that carry it]} and {fixture name: sha256} from the committed fixtures, or None."""
    base = out_root / FIXTURE_DIR_REL
    shas: dict[str, str] = {}
    seen: dict[tuple[str, str], list[str]] = {}
    for name in FIXTURE_NAMES:
        p = base / f"intelligence.states.{name}.json"
        if not p.is_file():
            return None
        raw = p.read_bytes()
        shas[name] = _sha(raw)
        states = json.loads(raw.decode("utf-8"))
        for eid, row in states.items():
            for a, v in (row.get("attributes") or {}).items():
                seen.setdefault((eid, a), []).append(name)
                if isinstance(v, dict):
                    for k in v:
                        seen.setdefault((eid, f"{a}.{k}"), []).append(name)
    return {"shas": shas, "seen": seen}


def honesty_for(ent: Ent, stale_after: float | None) -> list[str]:
    s = ["LIVE", "UNAVAILABLE", "UNKNOWN", "NOT_MEASURED"]
    if stale_after is not None:
        s.insert(1, "STALE")
    return s


def build_ledger(u: Universe, cat: dict, cat_bytes: bytes, live: dict | None, shape_bytes: bytes | None, fixtures: dict | None, T) -> dict:
    by_eid = {s["entity_id"]: s for s in cat["sources"]}
    redact = set(cat["redaction"]["extra_key_patterns"])
    card = u.card_reads
    rows = []
    for ent in sorted(u.entities, key=lambda e: e.ident):
        s = by_eid[ent.entity_id]
        stale_after = s["stale_after_s"]
        lstat = live["entities"][ent.entity_id] if live else None
        rows.append({
            "id": ent.ident, "kind": "source", "entity_id": ent.entity_id, "path": None, "origin": ent.origin, "group": s["group"],
            "priority": s["priority"], "coverage": "COVERED", "declared_by": [_source_tag(ent)],
            "honesty": honesty_for(ent, stale_after), "production_reads": ent.entity_id in card["entities"],
            "live": lstat, "live_type": None, "live_bytes": None, "value_policy": "shown", "seen_in": None})
        for a in s["attributes"]:
            path = a["name"]
            info = ent.attrs[path]
            top = path.split(".")[0]
            leaf = path.rsplit(".", 1)[-1]
            if "." in path:
                reads = leaf in card["blocks"].get(top, ()) or (top == "advice" and leaf in card["advice_keys"]) \
                    or (top == "decisions" and leaf in card["decision_labels"])
            else:
                reads = top in card["attributes"] and ent.origin == "integration"
            if "." not in path and top == "status" and ent.kind in ("status",):
                reads = "status" in card["attributes"]
            policy = "withheld" if any(r in path.lower() or r in leaf.lower() for r in redact if r) else "shown"
            la = live["attributes"].get((ent.entity_id, path)) if live else None
            seen = None
            if fixtures is not None:
                seen = sorted(fixtures["seen"].get((ent.entity_id, path), []))
            rows.append({
                "id": f"{ent.ident}#{path}", "kind": "attribute", "entity_id": ent.entity_id, "path": path, "origin": ent.origin,
                "group": s["group"], "priority": a["priority"], "coverage": "COVERED", "declared_by": sorted(info["tags"]),
                "honesty": ["LIVE", "NOT_MEASURED"] + (["STALE"] if stale_after is not None else []) +
                           (["WITHHELD"] if policy == "withheld" else []),
                "production_reads": bool(reads), "live": la["live"] if la else None,
                "live_type": la.get("type") if la else None, "live_bytes": la.get("bytes") if la else None,
                "value_policy": policy, "seen_in": seen, "note": (la or {}).get("why")})
    ledger = {
        "schema": LEDGER_SCHEMA, "view_id": VIEW_ID, "contract": u.contract_version,
        "id_rule": "a source row id is the catalogue source id; an attribute row id is '<source id>#<attribute name>'",
        "catalogue_sha256": _sha(cat_bytes), "live_shape_sha256": _sha(shape_bytes) if shape_bytes else None,
        "fixtures_sha256": fixtures["shas"] if fixtures else None,
        "vocabulary": {"coverage": list(COVERAGE_STATES), "live": list(LIVE_STATES), "honesty": list(HONESTY_STATES),
                       "exception_reasons": list(EXCEPTION_REASONS)},
        "rows": rows, "exceptions": cat["exceptions"],
        "live": None if live is None else {
            "filter": f"object id contains '{live['filter']}'", "live_entities": live["live_entities"],
            "undeclared": live["undeclared"], "not_present_live": live["not_present_live"],
            "not_checked_live": live["not_checked_live"]},
        "findings": sorted(set(u.findings) | set(_derived_findings(u, cat, live))),
        "diagnostics_covered": diag_covered(u, T),
        "dashboard": {"entities": u.dashboard_entities, "uncovered": sorted(set(u.dashboard_entities) - set(by_eid))},
    }
    ledger["totals"] = _totals(ledger)
    return ledger


def _source_tag(ent: Ent) -> str:
    return {"integration": "contract ENTITY_IDS and the integration's entity classes",
            "package": "home-assistant/packages YAML"}[ent.origin] if ent.kind not in ("pause_helper", "watchdog") \
        else "contract ENTITY_IDS (package entity) and home-assistant/packages YAML"


def _derived_findings(u: Universe, cat: dict, live: dict | None) -> list[str]:
    out = []
    if live is not None:
        for row in live["undeclared"]:
            out.append(f"UNDECLARED live: {row['entity_id']}" + (f" {row['path']}" if row["path"] else "") + f" - {row['why']}")
        for eid in live["not_checked_live"]:
            out.append(f"NOT_CHECKED_LIVE: {eid} is declared by a package but its name does not match the live listing's filter "
                       f"('{live['filter']}'), so the listing says nothing about it")
        for row in live["not_present_live"]:
            if row["path"] is None:
                out.append(f"NOT_PRESENT_LIVE: {row['entity_id']} - {row['why']}")
    unc = sorted(set(u.dashboard_entities) - {s["entity_id"] for s in cat["sources"]})
    for eid in unc:
        out.append(f"the dashboard references {eid}, which the catalogue does not cover")
    return out


def _totals(ledger: dict) -> dict:
    rows = ledger["rows"]
    live_rows = [r for r in rows if r["live"]]
    t = {"sources": sum(1 for r in rows if r["kind"] == "source"), "attributes": sum(1 for r in rows if r["kind"] == "attribute"),
         "covered": sum(1 for r in rows if r["coverage"] == "COVERED"), "exceptions": len(ledger["exceptions"]),
         "exceptions_by_reason": {k: sum(1 for e in ledger["exceptions"] if e["reason"] == k) for k in EXCEPTION_REASONS},
         "attributes_withheld_by_redaction": sum(1 for r in rows if r["value_policy"] == "withheld"),
         "production_reads": sum(1 for r in rows if r["production_reads"])}
    if ledger["live"] is not None:
        t["live"] = {k: sum(1 for r in live_rows if r["live"] == k) for k in LIVE_STATES if k != "UNDECLARED"}
        t["live"]["UNDECLARED"] = len(ledger["live"]["undeclared"])
    return t


# ---------------------------------------------------------------------------------------------------------------------
# the Markdown ledger
# ---------------------------------------------------------------------------------------------------------------------

def _cell(s) -> str:
    return str(s).replace("|", "/").replace("\n", " ")


def render_ledger_md(ledger: dict, cat: dict, T) -> str:
    t = ledger["totals"]
    L: list[str] = []
    w = L.append
    w("# Geek Mode information coverage ledger: ECCO Intelligence (SHADOW)")
    w("")
    w("GENERATED by `tools/geek_mode_coverage.py`. Do not edit by hand: `python tools/geek_mode_coverage.py --check` fails on any drift.")
    w("Machine form: `frontend/ecco-mode-shell/catalogue/intelligence.ledger.json`. Catalogue: "
      "`frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json` (schema `ecco-geek-catalogue/1`).")
    w("")
    w(f"- View: `{ledger['view_id']}`; contract `{ledger['contract']}`")
    w(f"- Catalogue sha256: `{ledger['catalogue_sha256']}`")
    if ledger["live_shape_sha256"]:
        w(f"- Live shape listing sha256: `{ledger['live_shape_sha256']}` (names, types and sizes only; no value)")
    else:
        w("- Live shape listing: not compared in this build")
    w("")
    w("## 1. Summary")
    w("")
    w(f"- Sources (entities): {t['sources']}; attribute rows: {t['attributes']}; every one COVERED ({t['covered']} of "
      f"{t['sources'] + t['attributes']}). Nothing that Home Assistant holds in a state or an attribute of this view is left out.")
    w(f"- Exceptions: {t['exceptions']} (information that is not a Home Assistant state, or is withheld): "
      + ", ".join(f"{k} {v}" for k, v in t["exceptions_by_reason"].items()) + ".")
    w(f"- Attribute rows whose VALUE the catalogue's redaction patterns withhold (the row is still listed): "
      f"{t['attributes_withheld_by_redaction']}.")
    w(f"- Rows whose attribute name is in the Production card's declared read lists today: {t['production_reads']} (a name match, not a "
      f"per-entity proof); every other row is reachable only in Geek Mode.")
    if "live" in t:
        lv = t["live"]
        w(f"- Live comparison: {lv['PRESENT_LIVE']} rows present live, {lv['NOT_PRESENT_LIVE']} declared but absent live "
          f"(conditional shapes, see section 5), {lv['NOT_CHECKED_LIVE']} not covered by the listing's filter, "
          f"{lv['UNDECLARED']} UNDECLARED (present live, declared nowhere).")
    w("")
    w("## 2. Findings the owner should see")
    w("")
    if ledger["findings"]:
        for f in ledger["findings"]:
            w(f"- {f}")
    else:
        w("- None.")
    w("")
    w("## 3. Vocabulary")
    w("")
    w("Coverage: `COVERED` (the source or attribute has a Geek Mode row) or `EXCEPTION` (listed in section 6 with a reason).")
    w("")
    w("Live comparison: `PRESENT_LIVE`, `NOT_PRESENT_LIVE` (declared, absent from the live entity), `NOT_CHECKED_LIVE` (outside the "
      "live listing's name filter), `UNDECLARED` (present live, declared by no code or package: a finding).")
    w("")
    w("Honesty states a Geek Mode row may show, in words and with an icon (never colour alone): " + ", ".join(f"`{x}`" for x in HONESTY_STATES) + ".")
    for k, v in T.HONESTY_WORDS:
        w(f"- `{k}`: {v}")
    w("")
    w("Exception reasons: " + ", ".join(f"`{x}`" for x in EXCEPTION_REASONS) + ".")
    w("")
    w("Row ids: a source row is the catalogue source id; an attribute row is `<source id>#<attribute name>`. A dotted name is one path "
      "into the first nesting level of a dict attribute; levels below that are shown in the raw (redacted) inspector under the parent "
      "attribute and are not counted separately. List attributes (`blockers`, `reason_codes`, `input_ages`) are one row each; the keys "
      "of a row of `input_ages` are name, age_s, limit_s and status, and of a row of `blockers` code and text.")
    w("")
    w("## 4. Sources and attributes")
    w("")
    by_src: dict = {}
    for r in ledger["rows"]:
        by_src.setdefault(r["entity_id"], []).append(r)
    src_meta = {s["entity_id"]: s for s in cat["sources"]}
    groups = {g["id"]: g for g in cat["groups"]}
    for s in cat["sources"]:
        rows = by_src[s["entity_id"]]
        head = rows[0]
        w(f"### {s['title']} (`{s['entity_id']}`)")
        w("")
        w(f"- Source id `{s['id']}`; origin {s['origin']}; group {groups[s['group']]['title']}; priority {s['priority']}; "
          f"unit {s['unit'] or 'none'}; live: {head['live'] or 'not compared'}; in the Production card's entity list: "
          f"{'yes' if head['production_reads'] else 'no'}")
        w(f"- Expected update {s['expected_update_s'] if s['expected_update_s'] is not None else 'not time-driven'} s; stale after "
          f"{s['stale_after_s'] if s['stale_after_s'] is not None else 'not age-judged'} s; honesty states: "
          + ", ".join(head["honesty"]))
        w("")
        w("| Attribute row | Priority | Declared by | In card read list | Live | Live type | Value | Fixtures |")
        w("|---|---|---|---|---|---|---|---|")
        for r in rows[1:]:
            seen = "n/a" if r["seen_in"] is None else (", ".join(r["seen_in"]) if r["seen_in"] else "none")
            lt = (r["live_type"] or "") + (f" {r['live_bytes']} B" if r["live_bytes"] else "")
            w(f"| `{_cell(r['path'])}` | {r['priority']} | {_cell('; '.join(r['declared_by']))} | {'yes' if r['production_reads'] else 'no'} | "
              f"{r['live'] or 'n/a'} | {_cell(lt.strip())} | {r['value_policy']} | {_cell(seen)} |")
        w("")
    w("## 5. Live comparison detail")
    w("")
    lv = ledger["live"]
    if lv is None:
        w("Not compared in this build (no live shape listing was given).")
    else:
        w(f"Filter of the listing: {lv['filter']}; entities in the listing: {lv['live_entities']}.")
        w("")
        w(f"- UNDECLARED: {len(lv['undeclared'])}")
        for r in lv["undeclared"]:
            w(f"  - `{r['entity_id']}`" + (f" `{r['path']}`" if r["path"] else "") + f": {r['why']}")
        w(f"- NOT_CHECKED_LIVE: {len(lv['not_checked_live'])}")
        for eid in lv["not_checked_live"]:
            w(f"  - `{eid}`")
        npl = [r for r in lv["not_present_live"] if r["path"] is not None]
        w(f"- NOT_PRESENT_LIVE entities: {sum(1 for r in lv['not_present_live'] if r['path'] is None)}; attributes: {len(npl)}")
        by_why: dict = {}
        for r in npl:
            by_why.setdefault(r["why"], []).append(f"{r['entity_id']} {r['path']}")
        for why, items in sorted(by_why.items()):
            w(f"  - {why} ({len(items)}):")
            for i in items:
                w(f"    - `{i}`")
    w("")
    w("## 6. Exceptions")
    w("")
    w("Every exception is information that is not a Home Assistant state or attribute, or that must not be shown. Nothing is excepted "
      "for convenience.")
    w("")
    w("| Id | What | Reason | Note |")
    w("|---|---|---|---|")
    for e in ledger["exceptions"]:
        w(f"| `{e['id']}` | {_cell(e['what'])} | {e['reason']} | {_cell(e['note'])} |")
    w("")
    w("Diagnostics download sections that are ALSO status attributes with a row (covered, so not exceptions): "
      + ", ".join(f"`{k}` as " + " and ".join(f"`{a}`" for a in v) for k, v in ledger["diagnostics_covered"].items()) + ".")
    w("")
    w("## 7. Dashboard check")
    w("")
    w("Entities that `home-assistant/dashboards/ecco_intelligence.yaml` references: " + ", ".join(f"`{e}`" for e in ledger["dashboard"]["entities"]) + ".")
    w(f"Not covered by the catalogue: {len(ledger['dashboard']['uncovered'])}.")
    w("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------------------------------------------------
# build everything, write or check
# ---------------------------------------------------------------------------------------------------------------------

def build_all(repo_root: Path, out_root: Path, shape_path: Path | None) -> dict:
    import geek_mode_texts_intelligence as T  # noqa: PLC0415 - the texts live beside the tool

    u = build_universe(repo_root)
    cat = build_catalogue(u, T)
    errs = validate_catalogue(cat)
    errs += coverage_problems(cat, u)
    if errs:
        raise CoverageError("\n".join(errs))
    cat_bytes = _json_bytes(cat, 4)
    live = shape_bytes = None
    if shape_path is not None:
        shape_bytes = shape_path.read_bytes()
        live = compare_live(u, load_shape(shape_path))
    fx = fixture_presence(out_root)
    ledger = build_ledger(u, cat, cat_bytes, live, shape_bytes, fx, T)
    md = render_ledger_md(ledger, cat, T)
    return {CATALOGUE_REL: cat_bytes, LEDGER_JSON_REL: _json_bytes(ledger, 2), LEDGER_MD_REL: md.encode("ascii")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare with the committed files instead of writing them")
    ap.add_argument("--repo-root", type=Path, default=REPO, help="the repository whose code is read (default: this one)")
    ap.add_argument("--out-root", type=Path, default=None, help="where the generated files live (default: the repo root)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--shape", type=Path, default=None, help=f"a live shape listing (default: the committed {SHAPE_REL})")
    g.add_argument("--no-shape", action="store_true", help="leave the live comparison out")
    args = ap.parse_args(argv)
    repo = args.repo_root.resolve()
    out = (args.out_root or repo).resolve()
    shape = None
    if not args.no_shape:
        shape = (args.shape or out / SHAPE_REL)
        if not shape.is_file():
            if args.shape is not None:
                print(f"ERROR: the live shape listing {shape} does not exist", file=sys.stderr)
                return 2
            shape = None
    try:
        files = build_all(repo, out, shape)
    except (UniverseError, CoverageError) as exc:
        print("geek-mode coverage FAILED:")
        for line in str(exc).splitlines():
            print(f"  FINDING: {line}")
        return 1
    if args.check:
        drift = []
        for rel, data in files.items():
            p = out / rel
            if not p.is_file():
                drift.append(f"{rel}: missing")
            elif p.read_bytes() != data:
                drift.append(f"{rel}: differs from a fresh regeneration")
        if drift:
            print("geek-mode coverage DRIFT:")
            for d in drift:
                print(f"  {d}")
            print("run: python tools/geek_mode_coverage.py   (then review the diff)")
            return 1
        print("geek-mode coverage files match a fresh regeneration")
        return 0
    for rel, data in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        print(f"wrote {rel} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
