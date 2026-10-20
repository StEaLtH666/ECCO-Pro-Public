#!/usr/bin/env python3
"""Firmware source assembler and navigator (S2a: tooling only, offline, no firmware change).

WHAT IT IS. The production firmware is one 1.4 MB ESPHome YAML file. The S1 design (design M) keeps that file as the ONLY
thing ESPHome, the write-surface analyser, the S0 equivalence checker and the proof chain ever read, and adds an optional
"source" view: ordered REGION fragments, grouped into review AREA files, which reassemble to the monolith BYTE FOR BYTE.
This tool implements that model and the navigation aids around it. At S2a nothing under `firmware/` is created or
changed: fragments exist only in caller-chosen directories outside the repository (tests use temp dirs).

AREAS ARE REVIEW AND NAVIGATION BOUNDARIES, NOT SAFETY ISOLATION. The firmware shares state across areas (the write mutex,
the configuration cache, snapshot flags, the 14 ordered intervals). Every safety argument is still made over the whole
monolith.

Model (text only; nothing is normalised except a uniformly CRLF file, which is read as LF and reported):
  - top-level SECTIONS start at a column-0 `key:` line. A section is a LIST section when its first content line is an
    item (`  - ...`). List ITEMS start at an exact `  - ` line.
  - ATTACHMENT: blank and comment lines before an item (or before a section key line) belong to the FOLLOWING unit, so a
    region boundary sits before them. Lines after the last content line of the file belong to the last unit.
  - a REGION is a run of whole units. Its MARKER line in an area file is `#@ecco-region <area>/<section>.<n>`.
  - the MANIFEST lists regions in emission order: `<area>/<section>.<n> <section> <anchor> [attach=prev]`, where the
    anchor is `start`, `key:<section>`, `id:<id>`, `name:<name>` or `item:<k>` (0-based index within the section).
    `attach=prev` starts the region at the anchor line itself, leaving its leading comments to the previous region.

Commands (read-only unless stated; every write goes ONLY to a caller-given path outside the repository):
  --check     --fragments DIR --manifest FILE   assemble and compare with the monolith: exit 0 equal, 1 stale, 2 input error
  --write     --fragments DIR --manifest FILE --output PATH   write the assembled text (never the canonical monolith)
  --split     --manifest FILE --out DIR         split the monolith into area files (DIR must not exist)
  --plan      [--areas a,b] [--sections s,..] [--lines A-B,..] [--out FILE]   candidate manifest from tools/firmware_areas.yaml
  --map       [--area A] [--items]              region (or item) table: lines, bytes, first/last item
  --where     ARG                               monolith line, fragment `file:line`, `yaml:LINE`, `#line N "..."` or a
                                                device-log header such as `[I][dump:I634]` (thousands digit is char-'0')
  --lookup    ID                                where an id is defined and which areas reference it (assign/call/read)
  --xref      [--area A]                        cross-area dependencies: ids defined in one area and used in another
  --diff-regions BASE [--head REV]              items changed between two git revisions, grouped by area (review aid)
  --validate-map                                check tools/firmware_areas.yaml against the monolith
Common: --monolith PATH or --rev REV (default: the working-tree monolith), --areas-file PATH, --json.

Exit codes: 0 ok / equal; 1 stale (well-formed but different); 2 input or structure error (fail closed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONOLITH_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
AREAS_REL = "tools/firmware_areas.yaml"
EXIT_OK, EXIT_STALE, EXIT_INPUT = 0, 1, 2
AREA_KEYS = ("core", "telemetry", "diagnostics", "modbus", "rtc", "arbitration", "tou", "free_power", "dump", "fallback")
MARKER_RE = re.compile(r"^#@ecco-region (?P<area>[a-z0-9_]+)/(?P<section>[a-z0-9_]+)\.(?P<n>[1-9][0-9]*)$")
MARKER_GRAMMAR_RE = re.compile(r"^#@ecco-region\b")
KEY_RE = re.compile(r"^(?P<key>[a-z_][a-z0-9_]*):(?:\s|$)")
ANY_KEY_RE = re.compile(r"^[^\s#-][^:]*:")  # any column-0 mapping key; must also satisfy KEY_RE (fail closed)
ITEM_RE = re.compile(r"^  - ")
DASH_RE = re.compile(r"^\s*- ")
FILLER_RE = re.compile(r"^\s*(#.*)?$")  # blank or comment-only line
ATTACHABLE_RE = re.compile(r"^(?:\s*|\s{0,2}#.*)$")  # attaches forward: blank, or a comment at indent <= 2
# FB-A header include, built at runtime so this file is not itself an includer (registry FB-A includer scan)
FBA_ANY_RE = re.compile("#" + r"\s*include\s*[<\"][^>\"]*" + "ecco_fallback" + r"_profile\.h|-" + r"\s*include/"
                        + "ecco_fallback" + r"_profile\.h")
ITEM_ID_RE = re.compile(r"^(?:  - |    )id:\s*(?P<v>[A-Za-z0-9_]+)\s*(?:#.*)?$")
ITEM_NAME_RE = re.compile(r"^(?:  - |    )name:\s*(?P<v>\"[^\"]*\"|'[^']*'|[^#\n]+?)\s*(?:#.*)?$")
ANCHOR_RE = re.compile(r"^(?:start|key:[a-z0-9_]+|id:[A-Za-z0-9_]+|name:\S+|item:[0-9]+)$")
REGION_NAME_RE = re.compile(r"^(?P<area>[a-z0-9_]+)/(?P<section>[a-z0-9_]+)\.(?P<n>[1-9][0-9]*)$")
ALLOWED_EXTRA_FILES = frozenset({"manifest.txt", "README.md"})


class InputError(Exception):
    """A fail-closed refusal: malformed input, unsafe path or a structure the model does not accept (exit 2)."""


def sha256(b: bytes | str) -> str:
    return hashlib.sha256(b.encode("utf-8") if isinstance(b, str) else b).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------
# Text and paths
# ---------------------------------------------------------------------------------------------------------------------


def decode_text(data: bytes, label: str) -> tuple[str, str]:
    """(LF text, original EOL kind). Refuses a BOM, non-UTF-8, a lone CR, mixed line endings and a missing final newline.
    A uniformly CRLF input is read as LF (kind 'crlf'); nothing else is ever rewritten."""
    if data.startswith(b"\xef\xbb\xbf"):
        raise InputError(f"{label}: starts with a UTF-8 BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"{label}: not UTF-8 ({exc.reason} at byte {exc.start})") from None
    if not text:
        raise InputError(f"{label}: empty")
    crlf = text.count("\r\n")
    cr = text.count("\r")
    lf = text.count("\n")
    if cr != crlf:
        raise InputError(f"{label}: contains a lone CR")
    if crlf and crlf != lf:
        raise InputError(f"{label}: mixed line endings ({crlf} CRLF, {lf - crlf} LF)")
    if not text.endswith("\n"):
        raise InputError(f"{label}: no final newline")
    return (text.replace("\r\n", "\n"), "crlf") if crlf else (text, "lf")


def require_outside_repo(path: Path, what: str) -> Path:
    """Refuse any output path inside this repository or inside ANY git work tree (other ECCO checkouts included), and
    refuse Windows device / UNC forms (`\\\\?\\...`, `\\\\server\\...`) outright. Containment is decided by FILE IDENTITY
    of every existing ancestor (os.path.samefile), so case variants, `..`, short names and junctions cannot escape it."""
    s = str(path)
    if s.startswith(("\\\\", "//")):
        raise InputError(f"{what} {s}: device and UNC paths are refused")
    p = Path(path).absolute()
    for anc in (p, *p.parents):
        if not anc.exists():
            continue
        if os.path.samefile(anc, ROOT):
            raise InputError(f"{what} {p} is inside the repository: S2a writes only outside it (no firmware/ file is created)")
        if (anc / ".git").exists():
            raise InputError(f"{what} {p} is inside a git work tree ({anc}): refused")
    try:
        p.resolve().relative_to(ROOT.resolve())
        raise InputError(f"{what} {p} resolves into the repository: refused")
    except ValueError:
        pass
    return p


@dataclass
class Monolith:
    text: str
    label: str
    eol: str

    @property
    def sha256_lf(self) -> str:
        return sha256(self.text)


def load_monolith(path: str | None = None, rev: str | None = None) -> Monolith:
    if path and rev:
        raise InputError("give --monolith or --rev, not both")
    if rev:
        r = subprocess.run(["git", "-C", str(ROOT), "cat-file", "blob", f"{rev}:{MONOLITH_REL}"], capture_output=True)
        if r.returncode != 0:
            raise InputError(f"cannot read {MONOLITH_REL} at {rev!r}: {r.stderr.decode('utf-8', 'replace').strip()}")
        text, eol = decode_text(r.stdout, f"{rev}:{MONOLITH_REL}")
        if eol != "lf":
            raise InputError(f"{rev}:{MONOLITH_REL}: the committed blob is CRLF; the canonical monolith must be LF")
        return Monolith(text, f"git:{rev}", eol)
    p = Path(path) if path else ROOT / MONOLITH_REL
    if not p.is_file():
        raise InputError(f"monolith {p} not found")
    try:  # a repository path is reported repo-relative, so no local absolute path ends up in a manifest or report
        label = p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        label = str(p)
    text, eol = decode_text(p.read_bytes(), label)
    return Monolith(text, label, eol)


# ---------------------------------------------------------------------------------------------------------------------
# Layout: sections, items, units (with the attachment rule)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Unit:
    kind: str            # 'head' | 'key' | 'item' | 'section' (a non-list section: key line + body)
    section: str         # top-level section ('head' for the file head)
    start: int           # 1-based first line, INCLUDING attached leading blank/comment lines
    bare: int            # 1-based line of the unit's own first line (the key line or the `  - ` line)
    end: int             # 1-based last line (inclusive)
    index: int = -1      # item index within its section
    ident: str = ""      # id:<id> | name:<name> | item:<k> | key:<s> | start
    item_id: str | None = None
    item_name: str | None = None
    area: str = "core"

    @property
    def nlines(self) -> int:
        return self.end - self.start + 1


@dataclass
class Layout:
    lines: list[str]                         # LF lines with their '\n'
    units: list[Unit]
    sections: dict[str, tuple[int, int]]     # name -> (key line, last line), in order
    list_sections: list[str]

    def unit_at(self, line: int) -> Unit:
        lo, hi = 0, len(self.units) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            u = self.units[mid]
            if line < u.start:
                hi = mid - 1
            elif line > u.end:
                lo = mid + 1
            else:
                return u
        raise InputError(f"line {line} is outside the monolith (1..{len(self.lines)})")

    def text_of(self, start: int, end: int) -> str:
        return "".join(self.lines[start - 1:end])

    def items(self, section: str | None = None) -> list[Unit]:
        return [u for u in self.units if u.kind == "item" and (section is None or u.section == section)]


def _strip_quotes(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def parse_layout(text: str) -> Layout:
    """Split LF text into units. Fails closed on any list-section line at indent < 4 that is neither an item start, a
    comment nor blank, and on marker grammar in the text."""
    lines = text.splitlines(keepends=True)
    if not lines or not text.endswith("\n"):
        raise InputError("text must be non-empty and end with a newline")
    for i, ln in enumerate(lines, 1):
        if MARKER_GRAMMAR_RE.match(ln):
            raise InputError(f"line {i}: region-marker grammar inside the firmware text")
        if ANY_KEY_RE.match(ln) and not KEY_RE.match(ln):
            raise InputError(f"line {i}: a column-0 key outside the accepted grammar [a-z_][a-z0-9_]*: {ln.strip()[:60]!r}")
    keys = [(i, m.group("key")) for i, ln in enumerate(lines, 1) if (m := KEY_RE.match(ln))]
    if not keys:
        raise InputError("no top-level section found")
    names = [k for _, k in keys]
    dup = sorted({k for k in names if names.count(k) > 1})
    if dup:
        raise InputError(f"duplicate top-level sections: {dup}")
    n = len(lines)
    sections: dict[str, tuple[int, int]] = {}
    for idx, (ln, key) in enumerate(keys):
        sections[key] = (ln, (keys[idx + 1][0] - 1) if idx + 1 < len(keys) else n)

    def is_filler(i: int) -> bool:
        return bool(FILLER_RE.match(lines[i - 1]))

    def attached_start(bare: int, floor: int) -> int:
        # only blank lines and comments at indent <= 2 attach forward; a deeper comment (e.g. `      #endif` closing a
        # lambda) stays with the item above it
        s = bare
        while s - 1 >= floor and ATTACHABLE_RE.match(lines[s - 2]):
            s -= 1
        return s

    raw: list[Unit] = []  # bare starts, ends filled below
    if keys[0][0] > 1:
        raw.append(Unit("head", "head", 1, 1, 0, ident="start"))
    list_sections = []
    for key, (kline, last) in sections.items():
        content = [i for i in range(kline + 1, last + 1) if not is_filler(i)]
        is_list = bool(content) and bool(ITEM_RE.match(lines[content[0] - 1]))
        if content and not is_list and DASH_RE.match(lines[content[0] - 1]):
            raise InputError(f"line {content[0]}: list section `{key}` with items at an indent other than 2 is not supported")
        if not is_list:
            raw.append(Unit("section", key, kline, kline, 0, ident=f"key:{key}"))
            continue
        list_sections.append(key)
        raw.append(Unit("key", key, kline, kline, 0, ident=f"key:{key}"))
        k = 0
        for i in content:
            ln = lines[i - 1]
            if ITEM_RE.match(ln):
                raw.append(Unit("item", key, i, i, 0, index=k))
                k += 1
            elif len(ln) - len(ln.lstrip(" ")) < 4:
                raise InputError(f"line {i}: in list section `{key}`, a content line at indent < 4 that is not an item")
    # attachment: each unit after the first starts after the previous unit's last content line
    for j, u in enumerate(raw):
        if j == 0:
            u.start = 1
        elif raw[j - 1].kind == "head":
            u.start = u.bare  # the file-head comment block stays the head unit; it is not attached to the first key
        else:
            u.start = attached_start(u.bare, raw[j - 1].bare + 1)
    for j, u in enumerate(raw):
        u.end = (raw[j + 1].start - 1) if j + 1 < len(raw) else n
    # identities
    for u in raw:
        if u.kind != "item":
            continue
        for i in range(u.bare, u.end + 1):
            ln = lines[i - 1].rstrip("\n")
            if i > u.bare and not ln.startswith("    ") and not FILLER_RE.match(ln):
                break
            m = ITEM_ID_RE.match(ln)
            if m and u.item_id is None:
                u.item_id = m.group("v")
        if u.item_id:
            u.ident = f"id:{u.item_id}"
        else:
            name = None
            for i in range(u.bare, u.end + 1):
                m = ITEM_NAME_RE.match(lines[i - 1].rstrip("\n"))
                if m:
                    name = _strip_quotes(m.group("v"))
                    break
            u.item_name = name
            # a manifest token cannot hold whitespace, so a spaced name is anchored by index there (the map matches names)
            u.ident = f"name:{name}" if name and re.fullmatch(r"\S+", name) else f"item:{u.index}"
    return Layout(lines, raw, sections, list_sections)


def strip_comments(code: str) -> str:
    """Drop YAML comment lines and C++ `//` line comments (string-aware enough for navigation, not a C++ parser)."""
    out = []
    for ln in code.split("\n"):
        if FILLER_RE.match(ln):
            continue
        res, i, q = [], 0, None
        while i < len(ln):
            c = ln[i]
            if q:
                res.append(c)
                if c == "\\" and i + 1 < len(ln):
                    res.append(ln[i + 1])
                    i += 2
                    continue
                if c == q:
                    q = None
            elif c in "\"'":
                q = c
                res.append(c)
            elif c == "/" and ln[i:i + 2] == "//":
                break
            elif c == "/" and ln[i:i + 2] == "/*":
                close = ln.find("*/", i + 2)
                if close < 0:
                    break  # a block comment that runs past the line: drop the rest (navigation heuristic)
                i = close + 2
                continue
            elif c == "#" and (i == 0 or ln[i - 1] in " \t") and not ln[:i].lstrip().startswith(("#", "\"", "'")) \
                    and q is None and ":" in ln[:i]:
                break  # a trailing YAML comment after a `key: value`
            else:
                res.append(c)
            i += 1
        out.append("".join(res))
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------------------
# Area map (tools/firmware_areas.yaml)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class AreaMap:
    data: dict
    warnings: list[str] = field(default_factory=list)


def load_area_map(path: str | Path | None = None) -> AreaMap:
    import yaml  # PyYAML (requirements-ci.txt); only the area map is YAML-parsed, never the firmware

    p = Path(path) if path else ROOT / AREAS_REL
    if not p.is_file():
        raise InputError(f"area map {p} not found")
    text, _ = decode_text(p.read_bytes(), str(p))
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or data.get("schema") != "ecco-firmware-areas/1":
        raise InputError(f"{p}: not an ecco-firmware-areas/1 document")
    areas = data.get("areas")
    if not isinstance(areas, dict) or tuple(areas) != AREA_KEYS:
        raise InputError(f"{p}: `areas` must list exactly {AREA_KEYS} in that order")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        raise InputError(f"{p}: `runs` missing")
    for r in runs:
        if not isinstance(r, dict) or set(r) - {"section", "first", "last", "area", "n"} or \
                not {"section", "first", "last", "area", "n"} <= set(r):
            raise InputError(f"{p}: malformed run {r!r}")
        if r["area"] not in AREA_KEYS:
            raise InputError(f"{p}: unknown area {r['area']!r}")
    return AreaMap(data)


def apply_area_map(layout: Layout, amap: AreaMap, mono: Monolith | None = None, strict: bool = False) -> list[str]:
    """Label every unit with its area. Non-item units are core. Every item must be covered by exactly one run, in order
    (fail closed). Returns warnings (for example a reviewed-against sha that differs from the current monolith)."""
    warnings = []
    reviewed = amap.data.get("monolith_sha256_lf")
    if mono is not None and reviewed and reviewed != mono.sha256_lf:
        msg = (f"area map was reviewed against monolith {reviewed[:12]}, current is {mono.sha256_lf[:12]}: "
               "labels are still resolved by anchor, but re-review the map")
        if strict:
            raise InputError(msg)
        warnings.append(msg)
    for u in layout.units:
        u.area = "core"
    by_section: dict[str, list[dict]] = {}
    for r in amap.data["runs"]:
        by_section.setdefault(r["section"], []).append(r)
    unknown = sorted(set(by_section) - set(layout.list_sections))
    if unknown:
        raise InputError(f"area map names sections that are not list sections: {unknown}")
    core_secs = amap.data.get("core_sections") or []
    if not isinstance(core_secs, list) or set(core_secs) & set(by_section) or set(core_secs) - set(layout.list_sections):
        raise InputError(f"area map: `core_sections` {core_secs!r} must be list sections that have no runs")
    for sec in layout.list_sections:
        items = layout.items(sec)
        if sec in core_secs:
            continue  # every item stays core
        if sec not in by_section:
            raise InputError(f"area map: list section `{sec}` has no runs and is not in core_sections")
        runs = by_section.get(sec, [])
        pos = 0
        for r in runs:
            if pos >= len(items):
                raise InputError(f"area map: run {r} starts after the end of `{sec}`")
            if not _ident_matches(items[pos], str(r["first"])):
                raise InputError(f"area map: `{sec}` run should start at {items[pos].ident} but says {r['first']!r}")
            n = int(r["n"])
            if n < 1 or pos + n > len(items):
                raise InputError(f"area map: run {r} has an impossible count")
            if not _ident_matches(items[pos + n - 1], str(r["last"])):
                raise InputError(f"area map: `{sec}` run of {n} from {r['first']!r} ends at {items[pos + n - 1].ident}, "
                                 f"not {r['last']!r}")
            for u in items[pos:pos + n]:
                u.area = r["area"]
            pos += n
        if pos != len(items):
            raise InputError(f"area map: `{sec}` covers {pos} of {len(items)} items")
    return warnings


def _ident_matches(u: Unit, token: str) -> bool:
    if token.startswith(("name:", "index:", "item:", "id:")):
        kind, _, val = token.partition(":")
        if kind == "index":
            kind = "item"
        if kind == "item":
            return u.index == int(val)
        if kind == "name":
            return u.item_id is None and u.item_name == val
        return u.ident == f"{kind}:{val}"
    return u.item_id == token


# ---------------------------------------------------------------------------------------------------------------------
# Regions, manifests, split and assemble
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class ManifestLine:
    region: str
    section: str
    anchor: str
    attach_prev: bool
    lineno: int

    @property
    def area(self) -> str:
        return self.region.split("/", 1)[0]


def parse_manifest(text: str, label: str = "manifest") -> list[ManifestLine]:
    out, seen = [], set()
    for i, raw in enumerate(text.split("\n"), 1):
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) not in (3, 4) or (len(parts) == 4 and parts[3] != "attach=prev"):
            raise InputError(f"{label}:{i}: expected `<area>/<section>.<n> <section> <anchor> [attach=prev]`")
        region, section, anchor = parts[:3]
        m = REGION_NAME_RE.match(region)
        if not m or m.group("area") not in AREA_KEYS:
            raise InputError(f"{label}:{i}: bad region name {region!r}")
        if m.group("section") != section:
            raise InputError(f"{label}:{i}: region {region} declares section {section!r}")
        if not ANCHOR_RE.match(anchor):
            raise InputError(f"{label}:{i}: bad anchor {anchor!r}")
        if region in seen:
            raise InputError(f"{label}:{i}: duplicate region {region}")
        seen.add(region)
        out.append(ManifestLine(region, section, anchor, len(parts) == 4, i))
    if not out:
        raise InputError(f"{label}: no regions")
    if out[0].anchor != "start" or out[0].attach_prev:
        raise InputError(f"{label}: the first region must have anchor `start`")
    if any(m.anchor == "start" for m in out[1:]):
        raise InputError(f"{label}: only the first region may have anchor `start`")
    return out


def render_manifest(mlines: list[ManifestLine], header: str = "") -> str:
    head = "".join(f"# {h}\n" for h in header.splitlines()) if header else ""
    return head + "".join(f"{m.region} {m.section} {m.anchor}{' attach=prev' if m.attach_prev else ''}\n" for m in mlines)


def _resolve_anchor(layout: Layout, m: ManifestLine) -> Unit:
    if m.anchor == "start":
        u = layout.units[0]
        if m.section != u.section:
            raise InputError(f"manifest {m.region}: `start` is in section {u.section!r}, not {m.section!r}")
        return u
    kind, _, val = m.anchor.partition(":")
    if kind == "key":
        hits = [u for u in layout.units if u.kind in ("key", "section") and u.section == val]
    else:
        hits = [u for u in layout.items(m.section) if _ident_matches(u, m.anchor)]
    if len(hits) != 1:
        raise InputError(f"manifest {m.region}: anchor {m.anchor!r} matches {len(hits)} units in `{m.section}`")
    u = hits[0]
    if u.section != m.section:
        raise InputError(f"manifest {m.region}: anchor {m.anchor!r} is in section {u.section!r}, not {m.section!r}")
    return u


def region_spans(layout: Layout, mlines: list[ManifestLine]) -> list[tuple[ManifestLine, int, int]]:
    """(manifest line, first line, last line) for every region, in emission order. Fails closed on order or anchors."""
    starts = []
    for m in mlines:
        u = _resolve_anchor(layout, m)
        starts.append(u.bare if m.attach_prev else u.start)
    for (a, sa), (b, sb) in zip(zip(mlines, starts), zip(mlines[1:], starts[1:])):
        if sb <= sa:
            raise InputError(f"manifest: region {b.region} (line {sb}) does not follow {a.region} (line {sa})")
    n = len(layout.lines)
    return [(m, s, (starts[i + 1] - 1) if i + 1 < len(starts) else n) for i, (m, s) in enumerate(zip(mlines, starts))]


def check_region_structure(layout: Layout, spans: list[tuple[ManifestLine, int, int]]) -> None:
    """Every region starts on a unit boundary (attachment rule, or the bare line with attach=prev) and its first
    non-blank, non-comment line is an item or a section key (or the file start)."""
    starts = {u.start: u for u in layout.units}
    bares = {u.bare: u for u in layout.units}
    for m, s, e in spans:
        if m.area != "core":
            # a non-core region holds ONLY items of its declared list section: no key line, no non-list section, no head
            if not m.anchor.startswith(("id:", "name:", "item:")):
                raise InputError(f"region {m.region}: a non-core region must be anchored on an item, not {m.anchor!r}")
            foreign = [u for u in layout.units if s <= u.bare <= e and (u.kind != "item" or u.section != m.section)]
            if foreign:
                f = foreign[0]
                raise InputError(f"region {m.region}: holds {f.kind} {f.ident or f.section!r} at line {f.bare}; a non-core "
                                 f"region may contain only `{m.section}` items")
        if m.attach_prev:
            if s not in bares:
                raise InputError(f"region {m.region}: attach=prev start {s} is not a unit's own first line")
        elif s not in starts:
            raise InputError(f"region {m.region}: start {s} is not a unit boundary under the attachment rule")
        first = next((i for i in range(s, e + 1) if not FILLER_RE.match(layout.lines[i - 1])), None)
        if first is None:
            raise InputError(f"region {m.region}: contains no content line")
        ln = layout.lines[first - 1]
        if not (ITEM_RE.match(ln) or KEY_RE.match(ln) or (m.anchor == "start" and s == 1)):
            raise InputError(f"region {m.region}: first content line {first} is neither an item nor a section key")


def split(mono: Monolith, mlines: list[ManifestLine]) -> dict[str, str]:
    """Area file name -> text (marker + region text, in emission order)."""
    layout = parse_layout(mono.text)
    spans = region_spans(layout, mlines)
    check_region_structure(layout, spans)
    check_include_placement(layout, spans)
    files: dict[str, list[str]] = {}
    for m, s, e in spans:
        files.setdefault(f"{m.area}.yaml", []).append(f"#@ecco-region {m.region}\n" + layout.text_of(s, e))
    return {k: "".join(v) for k, v in files.items()}


@dataclass
class Fragment:
    region: str
    file: str
    text: str
    marker_line: int  # 1-based line of the marker in its file


def parse_area_file(name: str, data: bytes) -> list[Fragment]:
    text, _ = decode_text(data, name)
    lines = text.splitlines(keepends=True)
    if not MARKER_RE.match(lines[0].rstrip("\n")):
        raise InputError(f"{name}: must begin with a `#@ecco-region` marker (no preamble)")
    frags, cur, cur_line, body = [], None, 0, []
    stem = name[:-5] if name.endswith(".yaml") else name
    for i, ln in enumerate(lines, 1):
        bare = ln.rstrip("\n")
        if MARKER_GRAMMAR_RE.match(bare):
            m = MARKER_RE.match(bare)
            if not m:
                raise InputError(f"{name}:{i}: malformed region marker {bare!r}")
            if m.group("area") != stem:
                raise InputError(f"{name}:{i}: region {m.group('area')}/... in file {name}")
            if cur is not None:
                if not body:
                    raise InputError(f"{name}:{cur_line}: region {cur} is empty")
                frags.append(Fragment(cur, name, "".join(body), cur_line))
            cur, cur_line, body = f"{m.group('area')}/{m.group('section')}.{m.group('n')}", i, []
        else:
            body.append(ln)
    if not body:
        raise InputError(f"{name}:{cur_line}: region {cur} is empty")
    frags.append(Fragment(cur, name, "".join(body), cur_line))
    return frags


def read_fragments(frag_dir: Path, mlines: list[ManifestLine]) -> dict[str, Fragment]:
    d = Path(frag_dir)
    if not d.is_dir():
        raise InputError(f"fragment directory {d} not found")
    expected = {f"{m.area}.yaml" for m in mlines}
    present = sorted(p.name for p in d.iterdir())
    for name in present:
        p = d / name
        if p.is_symlink() or not p.is_file():
            raise InputError(f"{p}: not a regular file (symlinks and directories are refused)")
        if name not in expected and name not in ALLOWED_EXTRA_FILES:
            raise InputError(f"{p}: unknown file in the fragment directory")
    missing = sorted(expected - set(present))
    if missing:
        raise InputError(f"fragment files missing: {missing}")
    order = {m.region: i for i, m in enumerate(mlines)}
    regions: dict[str, Fragment] = {}
    for name in sorted(expected):
        frags = parse_area_file(name, (d / name).read_bytes())
        idx = []
        for f in frags:
            if f.region in regions:
                raise InputError(f"{name}: region {f.region} appears more than once")
            if f.region not in order:
                raise InputError(f"{name}:{f.marker_line}: region {f.region} is not in the manifest")
            regions[f.region] = f
            idx.append(order[f.region])
        if idx != sorted(idx):
            raise InputError(f"{name}: regions are not in manifest order")
    absent = [m.region for m in mlines if m.region not in regions]
    if absent:
        raise InputError(f"manifest regions not found in any fragment file: {absent[:5]}")
    return regions


@dataclass
class Assembly:
    text: str
    origin: list[tuple[int, int, str, str, int]]  # (out first line, out last line, region, file, file first body line)


def assemble(frag_dir: Path, mlines: list[ManifestLine]) -> Assembly:
    regions = read_fragments(frag_dir, mlines)
    parts, origin, line = [], [], 1
    for m in mlines:
        f = regions[m.region]
        k = f.text.count("\n")
        parts.append(f.text)
        origin.append((line, line + k - 1, m.region, f.file, f.marker_line + 1))
        line += k
    text = "".join(parts)
    layout = parse_layout(text)
    spans = region_spans(layout, mlines)
    got = [(o[0], o[1]) for o in origin]
    if [(s, e) for _, s, e in spans] != got:
        bad = next(i for i, (a, b) in enumerate(zip([(s, e) for _, s, e in spans], got)) if a != b)
        raise InputError(f"region {mlines[bad].region}: emitted at lines {got[bad]}, but its anchor "
                         f"{mlines[bad].anchor!r} places it at {(spans[bad][1], spans[bad][2])}")
    check_region_structure(layout, spans)
    for (s, _e, region, _f, _b), m in zip(origin, mlines):
        sec = layout.unit_at(s).section
        if sec != m.section:
            raise InputError(f"region {region}: declared section {m.section!r}, but it starts in {sec!r}")
    check_include_placement(layout, spans)
    return Assembly(text, origin)


def check_include_placement(layout: Layout, spans: list[tuple[ManifestLine, int, int]]) -> None:
    """The FB-A header include (either form) occurs exactly once, inside a core region: core.yaml is the one declared
    includer at S2b (registry FB-A includer scan), so the line may never move into another area file."""
    hits = [i for i, ln in enumerate(layout.lines, 1) if FBA_ANY_RE.search(ln)]
    if len(hits) != 1:
        raise InputError(f"the FB-A header include must occur exactly once, found {len(hits)} at lines {hits[:5]}")
    for m, s, e in spans:
        if s <= hits[0] <= e and m.area != "core":
            raise InputError(f"region {m.region}: holds the FB-A header include (line {hits[0]}); it must stay in core")


def first_difference(a: str, b: str) -> int | None:
    la, lb = a.splitlines(keepends=True), b.splitlines(keepends=True)
    for i, (x, y) in enumerate(zip(la, lb), 1):
        if x != y:
            return i
    return None if len(la) == len(lb) else min(len(la), len(lb)) + 1


def origin_of(asm: Assembly, line: int) -> str:
    for s, e, region, file, body1 in asm.origin:
        if s <= line <= e:
            return f"{file}:{body1 + line - s} [{region}]"
    return "(past the end)"


# ---------------------------------------------------------------------------------------------------------------------
# Plans (candidate manifests) from the area map
# ---------------------------------------------------------------------------------------------------------------------


def plan(layout: Layout, areas: set[str] | None = None, sections: set[str] | None = None,
         line_ranges: list[tuple[int, int]] | None = None) -> list[ManifestLine]:
    """Candidate manifest. A unit leaves core when its area is selected (all non-core areas by default), its section is
    selected (all by default) and, with --lines, it lies inside one of the given ranges. Regions are maximal runs of
    consecutive units with the same area; numbering is per (area, section) in emission order."""
    def chosen(u: Unit) -> str:
        if u.kind != "item" or u.area == "core":
            return "core"
        if areas is not None and u.area not in areas:
            return "core"
        if sections is not None and u.section not in sections:
            return "core"
        if line_ranges is not None and not any(a <= u.start and u.end <= b for a, b in line_ranges):
            return "core"
        return u.area

    if line_ranges is not None:
        starts, ends = {u.start for u in layout.units}, {u.end for u in layout.units}
        for a, b in line_ranges:
            if a not in starts or b not in ends:
                raise InputError(f"--lines {a}-{b} does not fall on unit boundaries")
    out, counters, prev_area = [], {}, None
    for u in layout.units:
        a = chosen(u)
        if a == prev_area:
            continue
        prev_area = a
        key = (a, u.section)
        counters[key] = counters.get(key, 0) + 1
        out.append(ManifestLine(f"{a}/{u.section}.{counters[key]}", u.section, u.ident if u.ident else "start", False, 0))
    out[0].anchor = "start"
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Navigation: map, where, lookup, xref, diff-regions
# ---------------------------------------------------------------------------------------------------------------------

REF_ASSIGN = re.compile(r"\bid\((\w+)\)(?:\[[^\]]*\])?\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\bid\((\w+)\)\s*(?:\+\+|--)"
                        r"|(?:\+\+|--)\s*id\((\w+)\)")
REF_CALL = re.compile(r"\bid\((\w+)\)\s*(?:\.|->)\s*(\w+)\s*\(")
REF_ANY = re.compile(r"\bid\((\w+)\)")
YAML_ACTION_ID = re.compile(r"^\s+(?:-\s+)?(?:id|then_id):\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
YAML_ACTION_SHORT = re.compile(r"^\s+-\s+([a-z_]+(?:\.[a-z_]+)+):\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
YAML_ACTION_OPEN = re.compile(r"^\s+-\s+([a-z_]+(?:\.[a-z_]+)+):\s*$")
WRITE_ACTION_SUFFIXES = (".set", ".turn_on", ".turn_off", ".toggle", ".publish", ".increment", ".decrement", ".to_max",
                         ".to_min", ".set_index", ".next", ".previous", ".first", ".last", ".operation")
CALL_ACTIONS = frozenset({"script.execute", "script.stop", "component.update", "component.suspend", "component.resume"})


def action_kind(action: str | None) -> str:
    """Kind of a YAML action reference: globals.* and setters are writes ('assign'), script/component calls are 'call'."""
    if not action:
        return "action"
    if action.startswith("globals.") or action.endswith(WRITE_ACTION_SUFFIXES):
        return "assign"
    return "call" if action in CALL_ACTIONS else "read" if action == "script.wait" else "action"
READONLY_METHODS = frozenset({"state", "is_running", "get_state", "now", "has_state", "get_object_id", "get_name",
                              "is_on", "is_off", "size", "c_str", "empty", "find", "get_state_by_index", "active_index",
                              "current_option", "get", "value", "is_failed"})


def references(layout: Layout) -> dict[str, list[tuple[int, str, Unit]]]:
    """id -> [(line, kind, using unit)] with kind 'assign' | 'call' | 'read' | 'action'. Heuristic and labelled so:
    comments are stripped, C++ is not parsed."""
    refs: dict[str, list[tuple[int, str, Unit]]] = {}
    for u in layout.units:
        current_action = None
        for i in range(u.start, u.end + 1):
            raw = layout.lines[i - 1].rstrip("\n")
            if FILLER_RE.match(raw):
                continue
            code = strip_comments(raw)
            seen = set()
            for m in REF_ASSIGN.finditer(code):
                x = m.group(1) or m.group(2) or m.group(3)
                refs.setdefault(x, []).append((i, "assign", u))
                seen.add(x)
            for m in REF_CALL.finditer(code):
                x, meth = m.group(1), m.group(2)
                if x in seen:
                    continue
                refs.setdefault(x, []).append((i, "read" if meth in READONLY_METHODS else "call", u))
                seen.add(x)
            for m in REF_ANY.finditer(code):
                if m.group(1) not in seen:
                    refs.setdefault(m.group(1), []).append((i, "read", u))
                    seen.add(m.group(1))
            m = YAML_ACTION_SHORT.match(code)
            if m:
                refs.setdefault(m.group(2), []).append((i, action_kind(m.group(1)), u))
            m = YAML_ACTION_OPEN.match(code)
            if m:
                current_action = m.group(1)
            m = YAML_ACTION_ID.match(code)
            if m and not ITEM_ID_RE.match(code):  # an item-level `id:` is a definition, not a reference
                refs.setdefault(m.group(1), []).append((i, action_kind(current_action), u))
    return refs


def definitions(layout: Layout) -> dict[str, Unit]:
    out = {}
    for u in layout.units:
        if u.item_id:
            out.setdefault(u.item_id, u)
    return out


def region_rows(layout: Layout, mlines: list[ManifestLine]) -> list[dict]:
    rows = []
    for m, s, e in region_spans(layout, mlines):
        its = [u for u in layout.units if u.kind == "item" and s <= u.bare <= e]
        rows.append({"region": m.region, "area": m.area, "section": m.section, "first_line": s, "last_line": e,
                     "lines": e - s + 1, "bytes": len(layout.text_of(s, e).encode("utf-8")), "items": len(its),
                     "first": its[0].ident if its else m.anchor, "last": its[-1].ident if its else m.anchor})
    return rows


# `[L][tag:NNN]` or `[L][tag:XNNN]`; X (thousands) is '0' + n, so it can be ':' itself (10xxx) or a letter (25634 -> I634).
# The field is taken from the END of the bracket, so a ':' thousands character is still read correctly.
DEVICE_LOG_RE = re.compile(r"\[(?:VV|[EWIDCV])?\]\[(?P<tag>[^\]]*?):(?P<ln>[^\]]?[0-9]{3})\]")
# `#line N "file"`, `file.yaml:N`, PyYAML `in "file.yaml", line N` and ESPHome `file.yaml N:C`
YAML_LINE_RE = re.compile(r"(?:#line\s+(?P<a>\d+)\s+\"[^\"]*\"|\.yaml\"?:(?P<b>\d+)|\.yaml\",\s*line\s+(?P<c>\d+)"
                          r"|\.yaml\s+(?P<d>\d+):\d+)")
FRAGMENT_POS_RE = re.compile(r"(?:.*[\\/])?(?P<f>[a-z0-9_]+)\.yaml:(?P<l>\d+)")


def decode_log_line(field_: str) -> int:
    """ESPHome logger/log_buffer.h write_header: lines > 999 get 4 characters with the thousands digit written as
    '0' + thousands (so 25634 prints as 'I634'); smaller lines get exactly 3 digits."""
    if len(field_) == 4 and field_[1:].isdigit():
        return (ord(field_[0]) - ord("0")) * 1000 + int(field_[1:])
    if len(field_) == 3 and field_.isdigit():
        return int(field_)
    raise InputError(f"cannot decode device-log line field {field_!r}")


def resolve_where(arg: str, layout: Layout, mlines: list[ManifestLine] | None) -> int:
    a = arg.strip()
    m = DEVICE_LOG_RE.search(a)
    if m:
        return decode_log_line(m.group("ln"))
    m = FRAGMENT_POS_RE.fullmatch(a)
    if m and m.group("f") in AREA_KEYS:  # an area file position (any directory prefix); checked before `<file>.yaml:N`
        pass
    else:
        m = None
        y = YAML_LINE_RE.search(a)
        if y:
            return int(y.group("a") or y.group("b") or y.group("c") or y.group("d"))
        if a.isdigit():
            return int(a)
    if m:
        if mlines is None:
            raise InputError(f"{a}: a fragment position needs the --manifest that produced the fragments")
        fname, fline = f"{m.group('f')}.yaml", int(m.group("l"))
        pos = fragment_positions(layout, mlines)
        for (f, f1, f2), (s, _e) in pos:
            if f == fname and f1 <= fline <= f2:
                return s + (fline - f1)
        raise InputError(f"{a}: no region body covers that line (marker lines map to no monolith line)")
    raise InputError(f"cannot interpret {arg!r} (monolith line, file.yaml:N, yaml:N, #line, or a device-log header)")


def fragment_positions(layout: Layout, mlines: list[ManifestLine]) -> list[tuple[tuple[str, int, int], tuple[int, int]]]:
    """[((file, first body line, last body line), (monolith first, monolith last))] in emission order."""
    out, nxt = [], {}
    for m, s, e in region_spans(layout, mlines):
        f = f"{m.area}.yaml"
        marker = nxt.get(f, 1)
        out.append(((f, marker + 1, marker + (e - s + 1)), (s, e)))
        nxt[f] = marker + (e - s + 1) + 1
    return out


def describe_line(layout: Layout, line: int, mlines: list[ManifestLine] | None, hypothetical: bool = False) -> dict:
    """`hypothetical`: the manifest is the derived full ten-area plan, not one the caller gave, so the fragment position is
    where the line WOULD sit under that plan (labelled `fragment_if_full_plan`)."""
    u = layout.unit_at(line)
    d = {"monolith_line": line, "section": u.section, "unit": u.kind, "item": u.ident, "item_lines": [u.start, u.end],
         "area": u.area, "text": layout.lines[line - 1].rstrip("\n")[:160]}
    if mlines:
        for (f, f1, _f2), (s, e) in fragment_positions(layout, mlines):
            if s <= line <= e:
                d["fragment_if_full_plan" if hypothetical else "fragment"] = f"{f}:{f1 + line - s}"
                break
    return d


def diff_items(base: Layout, head: Layout) -> list[dict]:
    """Changed units between two layouts. Items are aligned per section by CONTENT (difflib over unit digests), so an
    inserted id-less item (an interval) is one 'added' row, not a cascade; non-item units are matched by section."""
    import difflib

    def row(change: str, sec: str, b: Unit | None, h: Unit | None) -> dict:
        u = h or b
        return {"change": change, "section": sec, "item": u.ident if u.kind == "item" else f"{u.kind}:{sec}",
                "area": u.area, "head_lines": [h.start, h.end] if h else None,
                "base_lines": [b.start, b.end] if b else None}

    def digest(layout: Layout, u: Unit) -> str:
        return sha256(layout.text_of(u.start, u.end))

    rows = []
    bnon = {(u.kind, u.section): u for u in base.units if u.kind != "item"}
    hnon = {(u.kind, u.section): u for u in head.units if u.kind != "item"}
    for k in sorted(set(bnon) | set(hnon), key=lambda k: ((hnon.get(k) or bnon.get(k)).start, k)):
        b, h = bnon.get(k), hnon.get(k)
        if b and h and digest(base, b) == digest(head, h):
            continue
        rows.append(row("added" if not b else "removed" if not h else "changed", k[1], b, h))
    for sec in dict.fromkeys(base.list_sections + head.list_sections):
        bi, hi = base.items(sec), head.items(sec)
        sm = difflib.SequenceMatcher(None, [digest(base, u) for u in bi], [digest(head, u) for u in hi], autojunk=False)
        for op, b0, b1, h0, h1 in sm.get_opcodes():
            if op == "equal":
                continue
            pairs = min(b1 - b0, h1 - h0) if op == "replace" else 0
            for j in range(pairs):
                rows.append(row("changed", sec, bi[b0 + j], hi[h0 + j]))
            for j in range(b0 + pairs, b1):
                rows.append(row("removed", sec, bi[j], None))
            for j in range(h0 + pairs, h1):
                rows.append(row("added", sec, None, hi[j]))
    rows.sort(key=lambda r: ((r["head_lines"] or r["base_lines"])[0], r["change"]))
    return rows


# ---------------------------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------------------------


def _labelled_layout(args, with_map: bool) -> tuple[Monolith, Layout, list[str]]:
    mono = load_monolith(args.monolith, args.rev)
    layout = parse_layout(mono.text)
    warnings = []
    if mono.eol == "crlf":
        warnings.append(f"{mono.label}: read a uniformly CRLF working copy as LF (git autocrlf); hashes are LF")
    if with_map == "strict":
        warnings += apply_area_map(layout, load_area_map(args.areas_file), mono, strict=args.strict_map)
    elif with_map == "lenient":
        # navigation must keep working on a firmware PR whose items the map does not cover yet: label everything core
        # and say so, instead of refusing (--validate-map and --plan stay strict)
        try:
            warnings += apply_area_map(layout, load_area_map(args.areas_file), mono, strict=args.strict_map)
        except InputError as exc:
            for u in layout.units:
                u.area = "core"
            warnings.append(f"area map does not cover this monolith ({exc}); every item is labelled core here - run "
                            "--validate-map and update tools/firmware_areas.yaml")
    return mono, layout, warnings


def _read_manifest(path: str) -> list[ManifestLine]:
    p = Path(path)
    if not p.is_file():
        raise InputError(f"manifest {p} not found")
    text, _ = decode_text(p.read_bytes(), str(p))
    return parse_manifest(text, str(p))


def _parse_ranges(spec: str) -> list[tuple[int, int]]:
    out = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)-(\d+)\s*", part)
        if not m or int(m.group(1)) > int(m.group(2)):
            raise InputError(f"bad line range {part!r}")
        out.append((int(m.group(1)), int(m.group(2))))
    return out


def _emit(obj, as_json: bool, render) -> None:
    if as_json:
        print(json.dumps(obj, indent=1, ensure_ascii=False))
    else:
        render(obj)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    g.add_argument("--split", action="store_true")
    g.add_argument("--plan", action="store_true")
    g.add_argument("--map", action="store_true")
    g.add_argument("--where", metavar="ARG")
    g.add_argument("--lookup", metavar="ID")
    g.add_argument("--xref", action="store_true")
    g.add_argument("--diff-regions", metavar="BASE")
    g.add_argument("--validate-map", action="store_true")
    ap.add_argument("--monolith", help="monolith path (default: the working-tree production YAML)")
    ap.add_argument("--rev", help="read the monolith blob at this git revision instead")
    ap.add_argument("--head", help="--diff-regions: head revision (default: the working-tree monolith)")
    ap.add_argument("--areas-file", help=f"area map (default {AREAS_REL})")
    ap.add_argument("--strict-map", action="store_true", help="refuse an area map reviewed against another monolith")
    ap.add_argument("--fragments", help="fragment directory (area files)")
    ap.add_argument("--manifest", help="manifest file")
    ap.add_argument("--output", help="--write: output path (outside the repository)")
    ap.add_argument("--out", help="--split: new directory / --plan: manifest file (outside the repository)")
    ap.add_argument("--area", help="filter to one area")
    ap.add_argument("--areas", help="--plan: comma-separated areas to split out (default: all non-core)")
    ap.add_argument("--sections", help="--plan: comma-separated sections to split (default: all)")
    ap.add_argument("--lines", help="--plan: comma-separated monolith line ranges A-B that may leave core")
    ap.add_argument("--items", action="store_true", help="--map: one row per item")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # the firmware text holds non-ASCII (e.g. U+2014); never emit cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        return _run(args)
    except InputError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except OSError as exc:  # an I/O failure is an input error, never "stale"
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_INPUT


def _run(args) -> int:
    if args.area and args.area not in AREA_KEYS:
        raise InputError(f"unknown area {args.area!r}; areas: {', '.join(AREA_KEYS)}")
    # --check / --write / --split never depend on navigation labels, so they need no area map
    mode = ("none" if (args.check or args.write or args.split or args.diff_regions)
            else "strict" if (args.plan or args.validate_map) else "lenient")
    mono, layout, warnings = _labelled_layout(args, with_map=mode)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    mlines = _read_manifest(args.manifest) if args.manifest else None

    if args.check or args.write:
        if not (args.fragments and mlines):
            raise InputError("--check/--write need --fragments and --manifest")
        asm = assemble(Path(args.fragments), mlines)
        if args.write:
            if not args.output:
                raise InputError("--write needs --output")
            out = require_outside_repo(Path(args.output), "--output")
            if out.exists():  # never overwrite, not even through a hard link to a tracked file
                raise InputError(f"--output {out} already exists (refusing to overwrite)")
            if out.resolve() == (ROOT / MONOLITH_REL).resolve():
                raise InputError("refusing to write the canonical monolith")
            out.write_bytes(asm.text.encode("utf-8"))
            print(f"wrote {out} ({len(asm.text.encode('utf-8'))} B, sha256 {sha256(asm.text)})")
            return EXIT_OK
        diff = first_difference(mono.text, asm.text)
        if diff is None:
            print(f"EQUAL: {len(mlines)} regions reassemble {mono.label} byte for byte (LF sha256 {mono.sha256_lf})")
            return EXIT_OK
        print(f"STALE: first difference at monolith:{diff} <- {origin_of(asm, diff)}")
        return EXIT_STALE

    if args.split:
        if not (mlines and args.out):
            raise InputError("--split needs --manifest and --out")
        out = require_outside_repo(Path(args.out), "--out")
        if out.exists():
            raise InputError(f"--out {out} already exists (refusing to overwrite)")
        files = split(mono, mlines)
        out.mkdir(parents=True)
        for name in sorted(files):
            (out / name).write_bytes(files[name].encode("utf-8"))
        (out / "manifest.txt").write_bytes(render_manifest(mlines).encode("utf-8"))
        print(f"split {mono.label} into {len(files)} area files, {len(mlines)} regions -> {out}")
        return EXIT_OK

    if args.plan:
        areas = set(args.areas.split(",")) if args.areas else None
        if areas and not areas <= set(AREA_KEYS) - {"core"}:
            raise InputError(f"--areas must name non-core areas ({', '.join(AREA_KEYS[1:])}): got {sorted(areas)}")
        secs = set(args.sections.split(",")) if args.sections else None
        if secs and not secs <= set(layout.list_sections):
            raise InputError(f"--sections must be list sections: {sorted(secs - set(layout.list_sections))}")
        ml = plan(layout, areas, secs, _parse_ranges(args.lines) if args.lines else None)
        text = render_manifest(ml, f"candidate manifest from {AREAS_REL} for {mono.label} (LF sha256 {mono.sha256_lf})")
        if args.out:
            out = require_outside_repo(Path(args.out), "--out")
            if out.exists():
                raise InputError(f"--out {out} already exists (refusing to overwrite)")
            out.write_bytes(text.encode("utf-8"))
            print(f"wrote {len(ml)} regions -> {out}")
        else:
            sys.stdout.write(text)
        return EXIT_OK

    if args.map:
        if args.items:
            rows = [{"first_line": u.start, "last_line": u.end, "section": u.section, "item": u.ident, "area": u.area,
                     "lines": u.nlines} for u in layout.units if u.kind == "item" and (not args.area or u.area == args.area)]
            cols = ["first_line", "last_line", "lines", "area", "section", "item"]
        else:
            rows = [r for r in region_rows(layout, mlines or plan(layout)) if not args.area or r["area"] == args.area]
            cols = ["first_line", "last_line", "lines", "bytes", "items", "region", "first", "last"]
        _emit(rows, args.json, lambda rs: [print("\t".join(cols))] + [print("\t".join(str(r[c]) for c in cols)) for r in rs])
        if not args.json:
            print("# areas are review/navigation boundaries, not safety isolation", file=sys.stderr)
        return EXIT_OK

    if args.where:
        line = resolve_where(args.where, layout, mlines)  # a fragment position needs the caller's manifest
        d = describe_line(layout, line, mlines or plan(layout), hypothetical=mlines is None)
        _emit(d, args.json, lambda x: print("\n".join(f"{k}: {v}" for k, v in x.items())))
        return EXIT_OK

    if args.lookup or args.xref:
        refs, defs = references(layout), definitions(layout)
        if args.lookup:
            x = args.lookup
            if x not in defs and x not in refs:
                raise InputError(f"id {x!r} is neither defined nor referenced in {mono.label}")
            u = defs.get(x)
            uses = refs.get(x, [])
            by_area: dict[str, dict[str, list[int]]] = {}
            for ln, kind, uu in uses:
                by_area.setdefault(uu.area, {}).setdefault(kind, []).append(ln)
            res = {"id": x, "defined": ({"line": u.bare, "item_lines": [u.start, u.end], "section": u.section,
                                         "area": u.area} if u else None),
                   "used_by": {a: {k: v for k, v in sorted(kinds.items())} for a, kinds in sorted(by_area.items())},
                   "cross_area": sorted(a for a in by_area if not u or a != u.area),
                   "note": "heuristic text scan (comments stripped, C++ not parsed); areas are not safety isolation"}

            def show(r):
                dd = r["defined"]
                print(f"{r['id']}: " + (f"defined at line {dd['line']} ({dd['section']}, area {dd['area']})" if dd
                                       else "not defined as an item id (component or header symbol)"))
                for a, kinds in r["used_by"].items():
                    print(f"  {a:12s} " + "; ".join(f"{k} {len(v)}x (first {v[0]})" for k, v in kinds.items()))
                if r["cross_area"]:
                    print(f"  cross-area: {', '.join(r['cross_area'])}")
            _emit(res, args.json, show)
            return EXIT_OK
        rows = []
        for x, uses in sorted(refs.items()):
            u = defs.get(x)
            if not u:
                continue
            others = {}
            for ln, kind, uu in uses:
                if uu.area != u.area:
                    others.setdefault(uu.area, set()).add(kind)
            if not others or (args.area and args.area != u.area and args.area not in others):
                continue
            rows.append({"id": x, "owner": u.area, "line": u.bare,
                         "used_by": {a: sorted(k) for a, k in sorted(others.items())}})
        _emit(rows, args.json, lambda rs: [print(f"{r['id']}\t{r['owner']}\t{r['line']}\t" +
                                                 ", ".join(f"{a}({'/'.join(k)})" for a, k in r["used_by"].items()))
                                           for r in rs])
        return EXIT_OK

    if args.diff_regions:
        base = parse_layout(load_monolith(rev=args.diff_regions).text)
        head = parse_layout(load_monolith(rev=args.head).text) if args.head else layout
        amap = load_area_map(args.areas_file)
        for lay in (base, head):
            try:
                apply_area_map(lay, amap)
            except InputError as exc:
                for u in lay.units:
                    u.area = "core"
                print(f"warning: area labels unavailable for one side ({exc}); items labelled core", file=sys.stderr)
        rows = diff_items(base, head)
        _emit(rows, args.json, lambda rs: [print(f"{r['change']:8s} {r['area']:12s} {r['section']:14s} {r['item']} "
                                                 f"head {r['head_lines']} base {r['base_lines']}") for r in rs]
              or print("no item changed"))
        return EXIT_OK

    if args.validate_map:
        counts: dict[str, int] = {}
        for u in layout.items():
            counts[u.area] = counts.get(u.area, 0) + 1
        print(f"area map OK for {mono.label}: {len(layout.items())} items in {len(layout.list_sections)} list sections; "
              + ", ".join(f"{a} {counts.get(a, 0)}" for a in AREA_KEYS))
        return EXIT_OK
    raise InputError("no command")


if __name__ == "__main__":
    sys.exit(main())
