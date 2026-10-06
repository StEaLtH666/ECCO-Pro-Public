#!/usr/bin/env python3
"""Render the generic ECCO tree for ONE site, without changing the tracked files.

The repository is generic: every Home Assistant entity id of the dongle uses the default device slug `ecco_clock_dongle` (the
slug a fresh Home Assistant install generates for the firmware's `name: ecco-clock-dongle`), and the Octopus Energy tariff
entities use the placeholders `your_meter_serial` / `your_import_mpan` / `your_export_mpan`. A site whose device slug or tariff
entities differ renders a COPY of the deployable files with its own values:

    python tools/ecco_site_render.py --site ecco_site.local.yaml              # writes dist/site/<same paths>
    python tools/ecco_site_render.py --site ecco_site.local.yaml --dry-run    # report only, write nothing
    python tools/ecco_site_render.py --site ecco_site.local.yaml --diff       # unified diff (tariff values masked)

The site file is local and git-ignored (`ecco_site.local.yaml`); `ecco_site.example.yaml` documents the schema. Nothing is
rendered in place: the output goes to --out (default dist/site, git-ignored). Deploy from the rendered copy.

EXACT RULES (no blind find-and-replace). Every occurrence of `ecco_clock_dongle` in a rendered file must be one of:
  entity      `<domain>.ecco_clock_dongle_<object>` for a Home Assistant domain an ESPHome node creates (DOMAINS): rendered to
              `<domain>.<device_slug>_<object>`, unless the site lists that entity id in keep_default_slug_entities or maps it
              in entity_map
  quoted      the bare slug between matching quotes or backticks (documentation of the slug): rendered to the device slug
  service     an ESPHome API action name `ecco_clock_dongle_<action>` (`esphome.` service or quoted id) for an action the
              firmware declares: KEPT (ESPHome derives it from the node name, not from Home Assistant's device slug)
  firmware    a firmware file name `ecco_clock_dongle_stage...`: KEPT
Anything else (an unknown context, a slug already carrying a prefix, a rendered tree used as input) is an error: the render
fails closed and writes nothing. Tariff placeholders are rendered only inside whole Octopus Energy entity ids; a placeholder
anywhere else, or one left after rendering, is an error. entity_map entries are exact entity ids matched at entity-id
boundaries; a mapped id that never occurs is an error. A site value that differs from the default but matches nothing is an
error (the expected source token is missing).

Standard library + PyYAML. No network. Writes only below --out.
"""

from __future__ import annotations

import argparse
import difflib
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "ecco-site/1"
DEFAULT_SLUG = "ecco_clock_dongle"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
MARKER = ".ecco-site-render"

# Home Assistant domains an ESPHome node's entities live in (the only places the device slug prefixes an entity id).
DOMAINS = ("binary_sensor", "button", "climate", "cover", "date", "datetime", "event", "fan", "light", "lock", "number",
           "select", "sensor", "switch", "text", "time", "update", "valve")

# The deployable files a site renders (repo-relative globs). Tests, registries and docs are never rendered.
RENDER_GLOBS = (
    "deployment/ha-manifest.yaml",
    "home-assistant/packages/*.yaml",
    "home-assistant/dashboards/*.yaml",
    "home-assistant/prototypes/**/*.yaml",
    "influxdb/*.yaml",
    "influxdb/**/*.flux",
    "frontend/*/examples/*.yaml",
    "frontend/*/dist/*.js",
    "frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js",
    "tools/ecco-flight-recorder*.ps1",
    "tools/ecco-snapshot.ps1",
    "tools/EccoFlightRecorderHelpers.psm1",
)

OCTOPUS_PLACEHOLDERS = ("your_meter_serial", "your_import_mpan", "your_export_mpan")
OCTOPUS_PUBLIC_ID = re.compile(r"octopus_energy_electricity_your_meter_serial_your_(import|export)_mpan_")
SLUG_RE = re.compile(r"[a-z][a-z0-9_]*[a-z0-9]")
ENTITY_ID_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z0-9][a-z0-9_]*")
METER_SERIAL_RE = re.compile(r"[a-z0-9]{6,20}")
MPAN_RE = re.compile(r"[0-9]{13}")
SITE_KEYS = {"schema", "device_slug", "keep_default_slug_entities", "octopus", "entity_map"}
OCTOPUS_KEYS = {"meter_serial", "import_mpan", "export_mpan"}


class RenderError(Exception):
    """The site file or the tree is not what the exact rules accept. Nothing has been written."""


@dataclass(frozen=True)
class Site:
    device_slug: str = DEFAULT_SLUG
    keep_default_slug_entities: tuple = ()
    octopus: dict | None = None
    entity_map: tuple = ()          # ((public entity id, site entity id), ...) sorted


@dataclass
class FileReport:
    rel: str
    sites: dict = field(default_factory=dict)       # kind -> count


# ---------------------------------------------------------------------------------------------------------------------------
# Site file
# ---------------------------------------------------------------------------------------------------------------------------
def parse_site(data) -> Site:
    """Validate a parsed site file strictly (unknown keys, shapes, duplicates) and return the Site."""
    if not isinstance(data, dict):
        raise RenderError("site file: the top level must be a mapping")
    unknown = set(data) - SITE_KEYS
    if unknown:
        raise RenderError(f"site file: unknown key(s) {sorted(unknown)} (allowed: {sorted(SITE_KEYS)})")
    if data.get("schema") != SCHEMA:
        raise RenderError(f"site file: schema must be {SCHEMA!r}")
    slug = data.get("device_slug")
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or "__" in slug:
        raise RenderError("site file: device_slug must be lower-case letters, digits and single underscores "
                          "(as Home Assistant spells a device slug), e.g. ecco_clock_dongle")
    keep = data.get("keep_default_slug_entities") or []
    if not isinstance(keep, list) or not all(isinstance(e, str) for e in keep):
        raise RenderError("site file: keep_default_slug_entities must be a list of entity ids")
    for e in keep:
        dom, _, obj = e.partition(".")
        if dom not in DOMAINS or not obj.startswith(DEFAULT_SLUG + "_") or not ENTITY_ID_RE.fullmatch(e):
            raise RenderError(f"site file: keep_default_slug_entities entry {e!r} is not a <domain>.{DEFAULT_SLUG}_<object> id")
    if len(set(keep)) != len(keep):
        raise RenderError("site file: duplicate keep_default_slug_entities entry")
    octo = data.get("octopus")
    if octo is not None:
        if not isinstance(octo, dict) or set(octo) != OCTOPUS_KEYS:
            raise RenderError(f"site file: octopus needs exactly the keys {sorted(OCTOPUS_KEYS)}")
        octo = {k: str(v) for k, v in octo.items()}
        if not METER_SERIAL_RE.fullmatch(octo["meter_serial"]):
            raise RenderError("site file: octopus.meter_serial must be the serial as Home Assistant spells it in the entity id "
                              "(lower-case letters and digits)")
        for k in ("import_mpan", "export_mpan"):
            if not MPAN_RE.fullmatch(octo[k]):
                raise RenderError(f"site file: octopus.{k} must be a 13-digit MPAN")
        if octo["import_mpan"] == octo["export_mpan"]:
            raise RenderError("site file: the import and export MPAN must differ")
    emap = data.get("entity_map") or {}
    if not isinstance(emap, dict):
        raise RenderError("site file: entity_map must be a mapping of entity id -> entity id")
    for src, dst in emap.items():
        if not (isinstance(src, str) and isinstance(dst, str) and ENTITY_ID_RE.fullmatch(src) and ENTITY_ID_RE.fullmatch(dst)):
            raise RenderError(f"site file: entity_map {src!r}: {dst!r} must map one full entity id to another")
        if src == dst:
            raise RenderError(f"site file: entity_map {src!r} maps to itself")
        if src in keep:
            raise RenderError(f"site file: {src!r} is both kept and mapped")
    return Site(device_slug=slug, keep_default_slug_entities=tuple(keep), octopus=octo,
                entity_map=tuple(sorted(emap.items())))


def load_site(path: Path) -> Site:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as ex:
        raise RenderError(f"cannot read the site file {path}: {ex}") from None
    try:
        return parse_site(yaml.safe_load(text))
    except yaml.YAMLError as ex:
        raise RenderError(f"site file {path}: not valid YAML ({ex})") from None


# ---------------------------------------------------------------------------------------------------------------------------
# The exact rules
# ---------------------------------------------------------------------------------------------------------------------------
def firmware_actions(root: Path) -> tuple:
    """The ESPHome API action names the firmware declares (their HA service names derive from the node name)."""
    fw = root / FIRMWARE_REL
    try:
        text = fw.read_text(encoding="utf-8")
    except OSError:
        raise RenderError(f"{FIRMWARE_REL} is missing: the ESPHome action names cannot be derived") from None
    names = tuple(sorted(set(re.findall(r"^    - action: ([a-z0-9_]+)\s*$", text, re.M))))
    if not names:
        raise RenderError(f"{FIRMWARE_REL} declares no API action: refusing to guess the service names")
    return names


_ENTITY_AT = re.compile(r"(?<![A-Za-z0-9_.])(" + "|".join(DOMAINS) + r")\.ecco_clock_dongle_([a-z0-9_*]*)")


def render_text(rel: str, text: str, site: Site, actions: tuple) -> tuple[str, dict]:
    """(rendered text, {kind: count}) for one file; raises RenderError on any occurrence the rules do not account for."""
    spans = []                      # (start, end, replacement, kind)
    counts: dict[str, int] = {}

    def add(s, e, rep, kind):
        spans.append((s, e, rep, kind))
        counts[kind] = counts.get(kind, 0) + 1

    keep = set(site.keep_default_slug_entities)
    emap = dict(site.entity_map)
    claimed = set()
    for m in _ENTITY_AT.finditer(text):
        ent = m.group(0)
        slug_at = m.start() + len(m.group(1)) + 1
        claimed.add(slug_at)
        if ent in emap:
            add(m.start(), m.end(), emap[ent], "entity_map")
        elif ent in keep:
            counts["kept_entity"] = counts.get("kept_entity", 0) + 1
        else:
            add(slug_at, slug_at + len(DEFAULT_SLUG), site.device_slug, "entity")
    action_re = re.compile(r"ecco_clock_dongle_(" + "|".join(map(re.escape, actions)) + r")(?![a-z0-9_])")
    for m in re.finditer(DEFAULT_SLUG, text):
        i = m.start()
        if i in claimed:
            continue
        before = text[i - 1] if i else ""
        after = text[m.end()] if m.end() < len(text) else ""
        if (before in "'\"`" and after == before):
            add(i, m.end(), site.device_slug, "quoted")
        elif action_re.match(text, i) and (text.endswith("esphome.", 0, i) or before in "'\"`"):
            counts["service_kept"] = counts.get("service_kept", 0) + 1
        elif text.startswith("ecco_clock_dongle_stage", i) and not (before.isalnum() or before == "_"):
            counts["firmware_name_kept"] = counts.get("firmware_name_kept", 0) + 1
        else:
            line = text.count("\n", 0, i) + 1
            raise RenderError(f"{rel}:{line}: '{DEFAULT_SLUG}' in a context the exact rules do not cover "
                              f"({text[max(0, i - 25):m.end() + 15]!r}); refusing to guess (is this already a rendered tree?)")
    # entity_map sources that are not dongle entities (exact entity-id boundaries)
    for src, dst in site.entity_map:
        if src.split(".", 1)[1].startswith(DEFAULT_SLUG + "_"):
            continue
        for m in re.finditer(r"(?<![A-Za-z0-9_.])" + re.escape(src) + r"(?![A-Za-z0-9_])", text):
            add(m.start(), m.end(), dst, "entity_map")
    # Octopus tariff ids
    for m in OCTOPUS_PUBLIC_ID.finditer(text):
        if site.octopus is None:
            counts["octopus_placeholder_left"] = counts.get("octopus_placeholder_left", 0) + 1
            continue
        mpan = site.octopus["import_mpan" if m.group(1) == "import" else "export_mpan"]
        add(m.start(), m.end(), f"octopus_energy_electricity_{site.octopus['meter_serial']}_{mpan}_", "octopus")
    covered = {p for m in OCTOPUS_PUBLIC_ID.finditer(text) for p in range(m.start(), m.end())}
    for ph in OCTOPUS_PLACEHOLDERS:
        for m in re.finditer(ph, text):
            if m.start() not in covered:
                line = text.count("\n", 0, m.start()) + 1
                raise RenderError(f"{rel}:{line}: tariff placeholder {ph!r} outside a whole Octopus Energy entity id")
    spans.sort()
    for (s1, e1, *_), (s2, *_) in zip(spans, spans[1:]):
        if s2 < e1:
            raise RenderError(f"{rel}: overlapping render sites at offsets {s1} and {s2} (ambiguous mapping)")
    out, pos = [], 0
    for s, e, rep, _k in spans:
        out.append(text[pos:s])
        out.append(rep)
        pos = e
    out.append(text[pos:])
    rendered = "".join(out)
    if site.octopus is not None:
        for ph in OCTOPUS_PLACEHOLDERS:
            if ph in rendered:
                raise RenderError(f"{rel}: tariff placeholder {ph!r} survived the render")
    return rendered, counts


def render_set(root: Path) -> list[str]:
    rels = set()
    for g in RENDER_GLOBS:
        for p in root.glob(g):
            if p.is_file() and not p.is_symlink() and "node_modules" not in p.parts:
                rels.add(p.relative_to(root).as_posix())
    return sorted(rels)


def render_tree(root: Path, site: Site) -> tuple[dict, list[FileReport]]:
    """{rel: (original bytes, rendered bytes)} for every file of the render set, and the per-file reports. Pure: reads only."""
    actions = firmware_actions(root)
    results, reports = {}, []
    for rel in render_set(root):
        raw = (root / rel).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise RenderError(f"{rel}: not UTF-8") from None
        rendered, counts = render_text(rel, text, site, actions)
        results[rel] = (raw, rendered.encode("utf-8"))
        reports.append(FileReport(rel, counts))
    total = lambda k: sum(r.sites.get(k, 0) for r in reports)  # noqa: E731
    if site.device_slug != DEFAULT_SLUG and total("entity") + total("quoted") == 0:
        raise RenderError(f"device_slug is {site.device_slug!r} but no '{DEFAULT_SLUG}' entity site was found: "
                          "the expected source token is missing (not a generic ECCO tree?)")
    if site.octopus is not None and total("octopus") == 0:
        raise RenderError("octopus values are configured but no Octopus Energy placeholder id was found: "
                          "the expected source token is missing")
    used = {k for k, _ in site.entity_map}
    for src in used:
        if not any(src.encode() in b for b, _ in results.values()):
            raise RenderError(f"entity_map source {src!r} does not occur in any rendered file")
    for e in site.keep_default_slug_entities:
        if not any(e.encode() in b for b, _ in results.values()):
            raise RenderError(f"keep_default_slug_entities entry {e!r} does not occur in any rendered file")
    return results, reports


def _mask(text: str, site: Site) -> str:
    if not site.octopus:
        return text
    for v in site.octopus.values():
        text = text.replace(v, "<" + "masked" + ">")
    return text


def _safe_out(out: Path, root: Path) -> Path:
    out = out.resolve()
    root = root.resolve()
    if out == root or root in out.parents:
        if not (out == root / "dist" or (root / "dist") in out.parents):
            raise RenderError(f"--out {out} is inside the repository but not under dist/ (git-ignored): refusing")
    if out.exists():
        if not out.is_dir() or out.is_symlink():
            raise RenderError(f"--out {out} exists and is not a plain directory")
        if any(out.iterdir()) and not (out / MARKER).is_file():
            raise RenderError(f"--out {out} is not empty and is not a previous render (no {MARKER}): refusing to overwrite")
    return out


def write_render(out: Path, root: Path, results: dict) -> int:
    out = _safe_out(out, root)
    if out.exists():
        shutil.rmtree(out)
    for rel, (_raw, data) in sorted(results.items()):
        dst = (out / rel).resolve()
        if out not in dst.parents:
            raise RenderError(f"{rel}: destination escapes --out")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    (out / MARKER).write_text("Rendered by tools/ecco_site_render.py. Site values inside: do not commit.\n", encoding="utf-8")
    return len(results)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, help="site file (git-ignored ecco_site.local.yaml; see ecco_site.example.yaml)")
    ap.add_argument("--root", default=str(REPO), help="the generic tree to render (default: this repository)")
    ap.add_argument("--out", default=None, help="output directory (default: <root>/dist/site)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report what would be rendered; write nothing")
    mode.add_argument("--diff", action="store_true", help="print a unified diff of the render (tariff values masked); write nothing")
    a = ap.parse_args(argv)
    root = Path(a.root)
    try:
        site = load_site(Path(a.site))
        results, reports = render_tree(root, site)
        changed = [r for r in reports if any(k in ("entity", "quoted", "octopus", "entity_map") for k in r.sites)]
        if a.diff:
            for rel, (raw, data) in sorted(results.items()):
                if raw != data:
                    sys.stdout.writelines(difflib.unified_diff(
                        raw.decode("utf-8").splitlines(True), _mask(data.decode("utf-8"), site).splitlines(True),
                        f"generic/{rel}", f"site/{rel}", n=0))
            return 0
        for r in reports:
            if r.sites:
                print(f"  {r.rel}: " + ", ".join(f"{k}={v}" for k, v in sorted(r.sites.items())))
        print(f"{len(results)} files in the render set, {len(changed)} changed for device slug {site.device_slug!r}"
              + (", tariff ids rendered" if site.octopus else ", tariff placeholders left generic"))
        if a.dry_run:
            print("dry run: nothing written")
            return 0
        n = write_render(Path(a.out) if a.out else root / "dist" / "site", root, results)
        print(f"wrote {n} files under {Path(a.out) if a.out else root / 'dist' / 'site'}")
        return 0
    except RenderError as ex:
        print(f"refused: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
