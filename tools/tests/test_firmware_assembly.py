#!/usr/bin/env python3
"""Regression suite: tools/assemble_firmware.py and tools/firmware_areas.yaml (firmware S2a, tooling only).

No firmware shape is pinned (the S0 C1 policy). Plans, anchors, mutation sites and expectations are derived from the
checked-out monolith (git HEAD blob) and the area map; the comparisons themselves are byte-exact. Fragments exist only in
temp dirs: nothing under firmware/ is created or changed (stage [9] proves it).

  [1] model       the layout parser finds exactly the items PyYAML finds, per list section, with the same ids and order;
                  the area map covers every item exactly once, in order, with the ten areas; the warning is present
  [2] A1-A8       for two derived plans, the S2b-style pilot (telemetry sensor regions only) and the full ten-area plan:
                  A1 assemble == monolith and region bytes sum to its size; A2 coverage, uniqueness, intra-file order;
                  A3 sections, anchors, unit boundaries, no marker grammar in the monolith, the attach=prev override;
                  A4 a re-split reproduces every area file byte for byte; A5 determinism (repeat, creation order,
                  PYTHONHASHSEED 0 vs another seed in subprocesses); A6 every area file parses and the items in
                  emission order equal the monolith's per-section (id, digest) sequence; A7 the FB-A include line sits
                  exactly once, in core.yaml only (pattern built at runtime); A8 --where decodes device-log headers,
                  including a line >= 10,000 (thousands digit = char - '0')
  [3] N1-N14      negative controls on temp copies, each refused with the expected exit code: 1-byte fragment edit;
                  monolith-only edit; swapped, dropped and duplicated manifest lines; an unknown fragment file; marker
                  grammar inside a region; lone CR, mixed EOL, BOM, missing final newline; out-of-order regions; a wrong
                  section label; non-UTF-8; a preamble; FB-A include line moved or duplicated; a region starting inside
                  an item
  [4] paths       outputs inside the repository, the canonical monolith as --output, an existing --out, a hostile region
                  name in a manifest and a symlinked fragment are refused (exit 2)
  [5] EOL         a uniformly CRLF area file and a CRLF monolith copy are read as LF; nothing else is normalised
  [6] navigation  --map, --where (monolith line, fragment file:line, yaml:N, #line, device log), --lookup and --xref on
                  ids derived from the map's own cross_area list; --diff-regions on a mutated item; timings reported
  [7] map rules   a wrong run count, a wrong first/last anchor, an unknown area and a missing section are refused; a
                  reviewed-against sha that differs only warns (and fails with --strict-map)
  [8] safety      AST scan of the tool (allow-listed imports; the only subprocess is git cat-file; no eval/exec/shell/
                  network); the new tools files spell neither the FB-A includer pattern nor the failback-shadow token
                  (both patterns built at runtime here)
  [9] untouched   the repository's firmware/ files are byte-identical before and after the suite

Test-only, no network. I/O: reads repo files and git blobs; writes only under temp dirs.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import assemble_firmware as A  # noqa: E402

TOOL = ROOT / "tools" / "assemble_firmware.py"
AREAS = ROOT / "tools" / "firmware_areas.yaml"
FAILURES: list[str] = []
# Built at runtime so this suite is neither an FB-A includer nor a failback-shadow reference.
FBA_LINE_RE = re.compile("-" + r"\s*include/" + "ecco_fallback" + r"_profile\.h")
FBA_ANY_RE = re.compile("#" + r"\s*include\s*[<\"][^>\"]*" + "ecco_fallback" + r"_profile\.h|" + FBA_LINE_RE.pattern)
FBS_TOKEN = "failback" + "_shadow"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name)
    if not ok:
        FAILURES.append(name + (f" :: {detail}" if detail else ""))


def cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if env:
        e.update(env)
    return subprocess.run([sys.executable, "-B", str(TOOL), *args], cwd=str(ROOT), capture_output=True, text=True,
                          env=e, encoding="utf-8")


def write_split(files: dict[str, str], d: Path, manifest: list[A.ManifestLine]) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for name in sorted(files):
        (d / name).write_bytes(files[name].encode("utf-8"))
    (d / "manifest.txt").write_bytes(A.render_manifest(manifest).encode("utf-8"))
    return d


def copy_split(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def mutate_file(p: Path, fn) -> None:
    p.write_bytes(fn(p.read_bytes()))


class Tagged(yaml.SafeLoader):
    pass


Tagged.add_multi_constructor("!", lambda loader, suffix, node: (
    loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
    else loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode)
    else loader.construct_mapping(node, deep=True)))


def ydigest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=False, default=str, ensure_ascii=False).encode()).hexdigest()


ALLOWED_IMPORTS = {"__future__", "argparse", "difflib", "hashlib", "json", "os", "re", "subprocess", "sys", "dataclasses",
                   "pathlib", "yaml"}
# `replace` is left out on purpose: str.replace and Path.replace are indistinguishable to the AST (rename is covered)
WRITE_ATTRS = {"write_bytes", "write_text", "mkdir", "unlink", "rename", "rmdir", "touch", "chmod",
               "symlink_to", "hardlink_to", "open"}


def tracked_firmware() -> dict[str, bytes]:
    """The git-tracked firmware/ files and their bytes (a local .esphome build tree is not part of the comparison)."""
    names = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "firmware/"], capture_output=True,
                           check=True).stdout.decode("utf-8").split("\0")
    return {n: (ROOT / n).read_bytes() for n in sorted(x for x in names if x)}


def ast_violations(src: str, allowed: set, write_attrs: set) -> list[str]:
    """Static safety scan of the tool: imports from an allow-list, no from-import or alias of os/subprocess, the only
    subprocess is `git -C <root> cat-file blob`, no eval/exec/compile/__import__/open(), and every file mutation call sits
    lexically inside the CLI handler `_run` (where each write is preceded by the path guard)."""
    tree = ast.parse(src)
    bad = []
    run_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run"), None)
    in_run = {id(x) for x in ast.walk(run_fn)} if run_fn else set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] not in allowed]
            bad += [f"import {a.name} as {a.asname}" for a in node.names if a.asname and a.name in {"os", "subprocess"}]
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod not in allowed or mod in {"os", "subprocess"}:
                bad.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in write_attrs and id(node) not in in_run:
                bad.append(f"file mutation .{f.attr}() outside _run (line {node.lineno})")
            if isinstance(f, ast.Name) and f.id in {"eval", "exec", "compile", "__import__", "open"}:
                bad.append(f"{f.id}() (line {node.lineno})")
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in {"os", "subprocess"}:
                if (f.value.id, f.attr) != ("subprocess", "run"):
                    bad.append(f"{f.value.id}.{f.attr}")
                else:
                    a0 = node.args[0] if node.args else None
                    ok = (isinstance(a0, ast.List) and len(a0.elts) >= 5
                          and [getattr(e, "value", None) for e in a0.elts[:1]] == ["git"]
                          and [getattr(e, "value", None) for e in a0.elts[3:5]] == ["cat-file", "blob"])
                    if not ok or any(k.arg == "shell" for k in node.keywords):
                        bad.append("subprocess.run(" + ast.unparse(a0) + ")")
            if isinstance(f, ast.Attribute) and f.attr in {"Popen", "system", "popen", "call", "check_output"}:
                bad.append(f".{f.attr}() (line {node.lineno})")
    return bad


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # failure details may quote non-ASCII firmware text
    fw_before = tracked_firmware()
    mono = A.load_monolith(rev="HEAD")
    layout = A.parse_layout(mono.text)
    amap = A.load_area_map(AREAS)
    warn = A.apply_area_map(layout, amap, mono)

    print("[1] model: layout parser vs PyYAML; area map coverage")
    doc = yaml.load(mono.text, Loader=Tagged)
    per_section_ok = all(
        [u.item_id for u in layout.items(s)] == [it.get("id") if isinstance(it, dict) else None for it in doc[s]]
        for s in layout.list_sections)
    yaml_lists = [k for k, v in doc.items() if isinstance(v, list)]
    check("list sections found by the parser == list sections in the YAML document", layout.list_sections == yaml_lists,
          f"{layout.list_sections} vs {yaml_lists}")
    check("per list section, the parser's items carry exactly PyYAML's ids, in order", per_section_ok)
    check("every non-item line belongs to core; every item is labelled with one of the ten areas",
          all(u.area == "core" for u in layout.units if u.kind != "item")
          and all(u.area in A.AREA_KEYS for u in layout.items()))
    used = {u.area for u in layout.items()}
    check("the map uses every non-core area at least once", set(A.AREA_KEYS) - {"core"} <= used, str(sorted(used)))
    check("the map states that areas are not safety isolation",
          "not safety isolation" in str(amap.data.get("warning", "")).lower())
    # A reviewed-against sha that differs is a WARNING by design (map header; tool default): a firmware PR must keep the
    # runs covering HEAD (checked above), but does not have to bump monolith_sha256_lf. Reported, never failed.
    print("  info  map reviewed against this monolith" if not warn else f"  info  map warning: {'; '.join(warn)}")
    print(f"  info  {len(layout.items())} items in {len(layout.list_sections)} list sections; "
          + ", ".join(f"{a} {sum(1 for u in layout.items() if u.area == a)}" for a in A.AREA_KEYS))

    plans = {
        "pilot": A.plan(layout, {"telemetry"}, {"sensor"}),
        "full": A.plan(layout),
    }
    check("the pilot plan moves only telemetry sensor regions", all(
        m.area == "core" or (m.area == "telemetry" and m.section == "sensor") for m in plans["pilot"])
        and any(m.area == "telemetry" for m in plans["pilot"]))
    check("the full plan uses every area file", {m.area for m in plans["full"]} == set(A.AREA_KEYS))

    tmp = Path(tempfile.mkdtemp(prefix="ecco_s2a_"))
    try:
        splits: dict[str, Path] = {}
        print("[2] A1-A8 on the derived pilot and full plans")
        for name, ml in plans.items():
            files = A.split(mono, ml)
            d = write_split(files, tmp / f"{name}_a", ml)
            splits[name] = d
            asm = A.assemble(d, ml)
            spans = A.region_spans(layout, ml)
            region_bytes = sum(len(layout.text_of(s, e).encode()) for _, s, e in spans)
            check(f"A1 {name}: assemble() == monolith byte for byte; region bytes sum to its size "
                  f"({len(ml)} regions, {len(files)} files)",
                  asm.text == mono.text and region_bytes == len(mono.text.encode()))
            regs = A.read_fragments(d, ml)
            check(f"A2 {name}: every manifest region is in exactly one file, no unknown file, intra-file order kept",
                  sorted(regs) == sorted(m.region for m in ml) and len(set(m.region for m in ml)) == len(ml))
            try:
                A.check_region_structure(layout, spans)
                a3 = all(A._resolve_anchor(layout, m).section == m.section for m in ml)
            except A.InputError as exc:
                a3 = False
                print("    ", exc)
            check(f"A3 {name}: sections, anchors and unit boundaries hold; no marker grammar in the monolith",
                  a3 and not any(A.MARKER_GRAMMAR_RE.match(ln) for ln in layout.lines))
            again = A.split(mono, A.parse_manifest((d / "manifest.txt").read_text(encoding="utf-8")))
            check(f"A4 {name}: a re-split from the written manifest reproduces every area file byte for byte",
                  again == {n: (d / n).read_text(encoding="utf-8") for n in files})
            d2 = tmp / f"{name}_rev"
            d2.mkdir()
            for n in sorted(files, reverse=True):
                (d2 / n).write_bytes(files[n].encode("utf-8"))
            check(f"A5 {name}: repeat split identical; reverse creation order assembles identically",
                  A.split(mono, ml) == files and A.assemble(d2, ml).text == asm.text)
            seq = {}
            parse_ok = True
            for m in ml:
                text = regs[m.region].text
                try:
                    obj = yaml.load(text, Loader=Tagged)
                except yaml.YAMLError as exc:
                    parse_ok = False
                    print("    ", m.region, exc)
                    continue
                if m.area == "core":
                    continue
                if not isinstance(obj, list):
                    parse_ok = False
                    continue
                seq.setdefault(m.section, []).extend(obj)
            for n in files:
                try:
                    yaml.load((d / n).read_text(encoding="utf-8"), Loader=Tagged)
                except yaml.YAMLError as exc:
                    parse_ok = False
                    print("    ", n, exc)
            moved_ok = True
            for sec, items in seq.items():
                # the monolith items that the plan moved out of core, by position, in monolith order
                idx = [u.index for m, s, e in spans if m.area != "core" for u in layout.items(sec) if s <= u.bare <= e]
                want = [doc[sec][i] for i in idx]
                if [ydigest(i) for i in items] != [ydigest(i) for i in want]:
                    moved_ok = False
            check(f"A6 {name}: every area file and region parses; moved items keep the monolith's (id, digest) order",
                  parse_ok and moved_ok)
            fba_files = [n for n, t in files.items() for ln in t.split("\n") if FBA_LINE_RE.search(ln)]
            check(f"A7 {name}: the FB-A include line appears exactly once, in core.yaml only", fba_files == ["core.yaml"],
                  str(fba_files))
        # A5 across hash seeds (subprocess, real CLI)
        outs = []
        for seed in ("0", "4242"):
            r1 = cli("--plan", env={"PYTHONHASHSEED": seed})
            r2 = cli("--map", "--json", env={"PYTHONHASHSEED": seed})
            outs.append((r1.returncode, r1.stdout, r2.returncode, r2.stdout))
        check("A5 CLI --plan and --map --json are identical under PYTHONHASHSEED 0 and 4242",
              outs[0] == outs[1] and outs[0][0] == 0 and outs[0][2] == 0, str([o[0] for o in outs]))
        pm = tmp / "seed_manifest.txt"
        pm.write_bytes(A.render_manifest(plans["full"]).encode("utf-8"))
        seeded = []
        for seed in ("0", "4242"):
            od = tmp / f"seed_split_{seed}"
            r = cli("--split", "--manifest", str(pm), "--out", str(od), "--rev", "HEAD", env={"PYTHONHASHSEED": seed})
            seeded.append((r.returncode, {p.name: p.read_bytes() for p in sorted(od.iterdir())} if od.is_dir() else {}))
        check("A5 CLI --split of the full plan writes byte-identical area files under PYTHONHASHSEED 0 and 4242",
              seeded[0] == seeded[1] and seeded[0][0] == 0 and len(seeded[0][1]) == len(A.AREA_KEYS) + 1)
        real_iterdir = Path.iterdir
        try:
            Path.iterdir = lambda self: iter(sorted(real_iterdir(self), key=lambda p: p.name, reverse=True))
            shuffled = A.assemble(splits["full"], plans["full"]).text
        finally:
            Path.iterdir = real_iterdir
        check("A5 a reversed directory listing (patched iterdir) assembles identically", shuffled == mono.text)
        # A3 attach=prev override: start the region after a filler run at its bare line
        ml = list(plans["pilot"])
        cand = [(i, A._resolve_anchor(layout, m)) for i, m in enumerate(ml) if i > 0]
        pick = next(((i, x) for i, x in cand if x.start < x.bare), None)
        if pick is None:
            check("A3 attach=prev: a pilot region starts with attached filler, to exercise the override", False)
        else:
            idx, u = pick
            ml_o = [A.ManifestLine(m.region, m.section, m.anchor, i == idx, 0) for i, m in enumerate(ml)]
            spans_o = A.region_spans(layout, ml_o)
            d = write_split(A.split(mono, ml_o), tmp / "attach_prev", ml_o)
            check(f"A3 attach=prev on {ml_o[idx].region} moves its {u.bare - u.start} leading filler line(s) to the "
                  "previous region and still reassembles exactly",
                  spans_o[idx][1] == u.bare and spans_o[idx - 1][2] == u.bare - 1 and A.assemble(d, ml_o).text == mono.text)
        # A8 --where
        big = next((x for x in layout.items() if x.bare >= 10000), None)
        if big is None:
            check("A8 a monolith line >= 10,000 exists to exercise the thousands-character decode", False)
        else:
            ln = big.bare
            hdr = f"[I][ecco:{chr(ord('0') + ln // 1000)}{ln % 1000:03d}]: message"
            r = cli("--where", hdr, "--json")
            got = json.loads(r.stdout) if r.returncode == 0 else {}
            check(f"A8 --where decodes device-log header {hdr.split(':')[0]}:{hdr.split(':')[1][:4]}] to line {ln}",
                  got.get("monolith_line") == ln and got.get("item") == big.ident, r.stderr[-300:])
        check("A8 decode_log_line: 'I634' -> 25634, ':500' -> 10500, '9999' -> 9999, '042' -> 42",
              (A.decode_log_line("I634"), A.decode_log_line(":500"), A.decode_log_line("9999"), A.decode_log_line("042"))
              == (25634, 10500, 9999, 42))

        print("[3] N1-N14 negative controls (temp copies)")
        base = splits["pilot"]
        pml = plans["pilot"]
        mfile = base / "manifest.txt"
        tel = "telemetry.yaml"

        def run_check(d: Path, manifest: Path | None = None, mono_path: str | None = None) -> tuple[int, str]:
            args = ["--check", "--fragments", str(d), "--manifest", str(manifest or d / "manifest.txt")]
            args += ["--monolith", mono_path] if mono_path else ["--rev", "HEAD"]
            r = cli(*args)
            return r.returncode, r.stdout + r.stderr

        code0, _ = run_check(base)
        check("N0 control: the untouched pilot split --check exits 0", code0 == 0)
        n = 0

        def neg(label: str, fn, want: int, reason: str, manifest_fn=None, mono_fn=None, mono_text=None) -> None:
            """Each control asserts the exit code AND the specific reason, so it fails if that one check is removed."""
            nonlocal n
            n += 1
            d = copy_split(base, tmp / f"neg{n}")
            if fn:
                fn(d)
            if manifest_fn:
                mutate_file(d / "manifest.txt", manifest_fn)
            mono_path = None
            if mono_fn or mono_text is not None:
                mp = tmp / f"neg{n}_mono.yaml"
                mp.write_bytes(mono_fn(mono.text.encode("utf-8")) if mono_fn else mono_text(d).encode("utf-8"))
                mono_path = str(mp)
            got, out = run_check(d, mono_path=mono_path)
            check(f"{label}: --check exits {want} ({reason!r})", got == want and reason in out, f"exit {got}: {out[-300:]}")

        def edit_one_byte(b: bytes) -> bytes:
            i = b.rfind(b"update_interval")
            return b[:i] + b"U" + b[i + 1:]

        def mid_newline(b: bytes) -> int:
            """A newline in the middle of a region BODY (not on a marker line, not the first or last byte)."""
            i = b.index(b"\n", len(b) // 2)
            while b[i + 1:i + 2] == b"#":
                i = b.index(b"\n", i + 1)
            return i

        neg("N1 a 1-byte fragment edit is STALE", lambda d: mutate_file(d / tel, edit_one_byte), 1, f"<- {tel}:")
        neg("N2 a monolith-only edit is STALE", None, 1, "STALE", mono_fn=edit_one_byte)
        tel_lines = [i for i, ln in enumerate(mfile.read_text(encoding="utf-8").split("\n")) if ln.startswith("telemetry/")]

        def swapper(i: int, j: int):
            def swap(b: bytes) -> bytes:
                ls = b.decode().split("\n")
                ls[i], ls[j] = ls[j], ls[i]
                return "\n".join(ls).encode()
            return swap

        def drop(b: bytes) -> bytes:
            ls = b.decode().split("\n")
            del ls[tel_lines[0]]
            return "\n".join(ls).encode()

        def dup(b: bytes) -> bytes:
            ls = b.decode().split("\n")
            ls.insert(tel_lines[0], ls[tel_lines[0]])
            return "\n".join(ls).encode()

        # across files the manifest stays well-formed but emits another order: STALE; within one file: refused
        neg("N3a swapped manifest lines (regions in different files) are STALE", None, 1, "STALE",
            manifest_fn=swapper(tel_lines[0], tel_lines[0] + 1))
        if len(tel_lines) >= 2:
            neg("N3b swapped manifest lines (two regions of one file) are refused", None, 2, "not in manifest order",
                manifest_fn=swapper(tel_lines[0], tel_lines[1]))
        else:
            check("N3b precondition: the pilot has at least two telemetry regions", False)
        neg("N4 a dropped manifest line is refused", None, 2, "is not in the manifest", manifest_fn=drop)
        neg("N5 a duplicated manifest line is refused", None, 2, "duplicate region", manifest_fn=dup)
        neg("N6 an unknown file in the fragment directory is refused",
            lambda d: (d / "x.yaml").write_bytes(b"#@ecco-region dump/sensor.1\n  - id: x\n"), 2, "unknown file")

        def inject_marker(d: Path) -> None:
            b = (d / tel).read_bytes()
            i = mid_newline(b)
            (d / tel).write_bytes(b[:i + 1] + b"#@ecco-region telemetry/sensor\n" + b[i + 1:])

        neg("N7 marker grammar inside a region is refused", inject_marker, 2, "malformed region marker")
        neg("N8a a lone CR inside a region body is refused",
            lambda d: mutate_file(d / tel, lambda b: b[:mid_newline(b)] + b"\r" + b[mid_newline(b) + 1:]), 2, "lone CR")
        neg("N8b mixed line endings inside a region body are refused",
            lambda d: mutate_file(d / tel, lambda b: b[:mid_newline(b)] + b"\r\n" + b[mid_newline(b) + 1:]), 2,
            "mixed line endings")
        neg("N8c a BOM is refused", lambda d: mutate_file(d / tel, lambda b: b"\xef\xbb\xbf" + b), 2, "BOM")
        neg("N8d a missing final newline is refused", lambda d: mutate_file(d / tel, lambda b: b.rstrip(b"\n")), 2,
            "no final newline")

        def reorder(d: Path) -> None:
            frags = A.parse_area_file(tel, (d / tel).read_bytes())
            body = "".join(f"#@ecco-region {f.region}\n{f.text}" for f in [frags[1], frags[0], *frags[2:]])
            (d / tel).write_bytes(body.encode())

        if sum(1 for m in pml if m.area == "telemetry") >= 2:
            neg("N9 out-of-order regions in an area file are refused", reorder, 2, "not in manifest order")
        else:
            check("N9 precondition: the pilot has at least two telemetry regions", False)
        first_tel = next(m for m in pml if m.area == "telemetry")
        wrong = next(s for s in layout.list_sections if s != first_tel.section)
        old_name, new_name = first_tel.region, f"telemetry/{wrong}.9"
        neg("N10 a wrong section label (region relabelled to another section) is refused",
            lambda d: mutate_file(d / tel, lambda b: b.replace(f"#@ecco-region {old_name}\n".encode(),
                                                               f"#@ecco-region {new_name}\n".encode())), 2,
            f"in `{wrong}`", manifest_fn=lambda b: b.replace(f"{old_name} {first_tel.section} ".encode(),
                                                             f"{new_name} {wrong} ".encode()))
        neg("N11 non-UTF-8 is refused", lambda d: mutate_file(d / tel, lambda b: b.replace(b"template", b"templ\xffte", 1)),
            2, "not UTF-8")
        neg("N12 a preamble before the first marker is refused",
            lambda d: mutate_file(d / tel, lambda b: b"# preamble\n" + b), 2, "no preamble")

        # N13: the FB-A include line removed, moved or duplicated. The monolith is REGENERATED from the mutated
        # fragments, so the bytes agree and only the placement rule can refuse it.
        def regenerated(d: Path) -> str:
            ml = A.parse_manifest((d / "manifest.txt").read_text(encoding="utf-8"))
            frags = {f.region: f for name in sorted({f"{m.area}.yaml" for m in ml})
                     for f in A.parse_area_file(name, (d / name).read_bytes())}
            return "".join(frags[m.region].text for m in ml)

        inc = next(ln for ln in mono.text.split("\n") if FBA_LINE_RE.search(ln)) + "\n"
        neg("N13a the FB-A include line removed from core.yaml (monolith regenerated) is refused",
            lambda d: mutate_file(d / "core.yaml", lambda b: b.replace(inc.encode(), b"", 1)), 2, "found 0",
            mono_text=regenerated)
        neg("N13b the FB-A include line moved into telemetry.yaml (monolith regenerated) is refused",
            lambda d: (mutate_file(d / "core.yaml", lambda b: b.replace(inc.encode(), b"", 1)),
                       mutate_file(d / tel, lambda b: b + inc.encode())), 2, "must stay in core", mono_text=regenerated)
        neg("N13c the FB-A include line duplicated into telemetry.yaml (monolith regenerated) is refused",
            lambda d: mutate_file(d / tel, lambda b: b + inc.encode()), 2, "found 2", mono_text=regenerated)

        # N14 (byte-preserving): split one telemetry region into two adjacent regions of the same file, then move the
        # second marker down one line, so it starts inside an item. The assembled bytes are UNCHANGED, so only the
        # boundary / start-line rules can refuse it.
        big = next((m, s, e) for m, s, e in A.region_spans(layout, pml) if m.area == "telemetry"
                   and sum(1 for u in layout.items(m.section) if s <= u.bare <= e) >= 2)
        second = [u for u in layout.items(big[0].section) if big[1] <= u.bare <= big[2]][1]
        k = pml.index(big[0])
        ml14 = pml[:k + 1] + [A.ManifestLine("telemetry/sensor.50", big[0].section, second.ident, False, 0)] + pml[k + 1:]
        d14 = write_split(A.split(mono, ml14), tmp / "n14", ml14)
        code14, _ = run_check(d14)
        check("N14 control: the two-region variant itself assembles exactly (exit 0)", code14 == 0)

        def shift_marker(d: Path) -> None:
            lines_ = (d / tel).read_text(encoding="utf-8").split("\n")
            i = lines_.index("#@ecco-region telemetry/sensor.50")
            lines_[i], lines_[i + 1] = lines_[i + 1], lines_[i]
            (d / tel).write_bytes("\n".join(lines_).encode())

        shifted = copy_split(d14, tmp / "n14_shift")
        shift_marker(shifted)
        same_bytes = regenerated(shifted) == mono.text
        code, out = run_check(shifted)
        check("N14 a region that starts inside an item is refused although the assembled bytes are unchanged",
              same_bytes and code == 2 and "places it at" in out, f"same_bytes={same_bytes} exit {code}: {out[-300:]}")

        print("[4] paths and outputs")
        r = cli("--split", "--manifest", str(mfile), "--out", str(ROOT / "dist" / "s2a_should_not_exist"), "--rev", "HEAD")
        check("--split --out inside the repository is refused (exit 2)", r.returncode == 2 and not (ROOT / "dist" /
                                                                                                  "s2a_should_not_exist").exists())
        r = cli("--write", "--fragments", str(base), "--manifest", str(mfile), "--output", str(ROOT / A.MONOLITH_REL))
        check("--write to the canonical monolith is refused (exit 2)", r.returncode == 2)
        r = cli("--plan", "--out", str(ROOT / "tools" / "s2a_manifest.txt"))
        check("--plan --out inside the repository is refused (exit 2)", r.returncode == 2 and
              not (ROOT / "tools" / "s2a_manifest.txt").exists())
        r = cli("--split", "--manifest", str(mfile), "--out", str(base), "--rev", "HEAD")
        check("--split onto an existing directory is refused (exit 2)", r.returncode == 2)
        dev = "\\\\?\\" + str(ROOT / A.MONOLITH_REL)  # Windows device-path form (backslash x2, ?, backslash)
        r = cli("--write", "--fragments", str(base), "--manifest", str(mfile), "--output", dev)
        check("a device / UNC form of the canonical monolith as --output is refused (exit 2)",
              r.returncode == 2 and "UNC" in r.stderr, r.stderr[-200:])
        other = tmp / "other_checkout"
        (other / ".git").mkdir(parents=True)
        r = cli("--write", "--fragments", str(base), "--manifest", str(mfile), "--output", str(other / "x.yaml"))
        check("--output inside ANY git work tree (another checkout) is refused (exit 2)",
              r.returncode == 2 and "git work tree" in r.stderr and not (other / "x.yaml").exists(), r.stderr[-200:])
        r = cli("--write", "--fragments", str(base), "--manifest", str(mfile), "--output", str(tmp / "no" / "dir" / "x.yaml"))
        check("an I/O failure (missing --output parent) is an input error (exit 2), never STALE",
              r.returncode == 2 and ("No such file" in r.stderr or "cannot find the path" in r.stderr.lower()),
              r.stderr[-200:])
        out = tmp / "assembled.yaml"
        r = cli("--write", "--fragments", str(base), "--manifest", str(mfile), "--output", str(out))
        check("--write to a new path outside the repository writes the exact monolith",
              r.returncode == 0 and out.read_bytes() == mono.text.encode("utf-8"), r.stderr[-200:])
        before = out.read_bytes()
        r = cli("--write", "--fragments", str(base), "--manifest", str(mfile), "--output", str(out))
        check("--write onto an existing --output is refused (exit 2) and leaves it untouched",
              r.returncode == 2 and "already exists" in r.stderr and out.read_bytes() == before, r.stderr[-200:])
        hostile = tmp / "hostile_manifest.txt"
        hostile.write_bytes(b"core/head.1 head start\n../evil/sensor.1 sensor id:x\n")
        r = cli("--check", "--fragments", str(base), "--manifest", str(hostile), "--rev", "HEAD")
        check("a manifest region name with a path component is refused (exit 2)",
              r.returncode == 2 and "bad region name" in r.stderr, r.stderr[-200:])
        try:
            dl = copy_split(base, tmp / "symlink")
            (dl / tel).unlink()
            os.symlink(base / tel, dl / tel)
            r = cli("--check", "--fragments", str(dl), "--manifest", str(mfile), "--rev", "HEAD")
            check("a symlinked fragment file is refused (exit 2)", r.returncode == 2 and "symlinks" in r.stderr,
                  r.stderr[-200:])
        except (OSError, NotImplementedError):
            print("  SKIP  symlinked fragment: this platform/user cannot create symlinks (not counted as a pass)")

        print("[5] line endings")
        dc = copy_split(base, tmp / "crlf")
        mutate_file(dc / tel, lambda b: b.replace(b"\n", b"\r\n"))
        check("a uniformly CRLF area file is read as LF and still assembles exactly", run_check(dc)[0] == 0)
        mp = tmp / "mono_crlf.yaml"
        mp.write_bytes(mono.text.replace("\n", "\r\n").encode("utf-8"))
        r = cli("--check", "--fragments", str(base), "--manifest", str(mfile), "--monolith", str(mp))
        check("a uniformly CRLF monolith copy is read as LF (with a warning) and compares equal",
              r.returncode == 0 and "CRLF" in r.stderr, r.stderr[-200:])

        print("[6] navigation")
        timings = {}
        t0 = time.perf_counter()
        r = cli("--map", "--json")
        timings["--map"] = time.perf_counter() - t0
        rows = json.loads(r.stdout) if r.returncode == 0 else []
        check("--map lists every full-plan region and their lines add up to the monolith",
              len(rows) == len(plans["full"]) and sum(x["lines"] for x in rows) == len(layout.lines))
        some_area = next(a for a in A.AREA_KEYS if a != "core")
        r = cli("--map", "--area", some_area, "--items", "--json")
        check(f"--map --area {some_area} --items lists exactly that area's items",
              r.returncode == 0 and len(json.loads(r.stdout)) == sum(1 for u in layout.items() if u.area == some_area))
        probe = next(u for u in layout.items() if u.area not in ("core",) and u.item_id)
        t0 = time.perf_counter()
        r = cli("--where", str(probe.bare + 1), "--json")
        timings["--where line"] = time.perf_counter() - t0
        w = json.loads(r.stdout) if r.returncode == 0 else {}
        check("--where <monolith line> names the item, its area and the hypothetical full-plan fragment position",
              w.get("item") == probe.ident and w.get("area") == probe.area and "fragment" not in w
              and ".yaml:" in str(w.get("fragment_if_full_plan")))
        frag = w.get("fragment_if_full_plan")
        if frag:
            r2 = cli("--where", frag, "--manifest", str(pm), "--json")
            back = json.loads(r2.stdout).get("monolith_line") if r2.returncode == 0 else None
            check("--where <fragment file:line> --manifest <full plan> maps back to the same monolith line",
                  back == probe.bare + 1, r2.stderr[-200:])
            r3 = cli("--where", "firmware/src/" + frag, "--manifest", str(pm), "--json")
            back3 = json.loads(r3.stdout).get("monolith_line") if r3.returncode == 0 else None
            check("--where accepts a path-prefixed fragment position (firmware/src/<area>.yaml:N)", back3 == probe.bare + 1)
            r4 = cli("--where", frag)
            check("--where <fragment file:line> without --manifest is refused (exit 2), never silently guessed",
                  r4.returncode == 2)
        for form in ('in "x.yaml", line 1234, column 5', "x.yaml 1234:5"):
            r = cli("--where", form, "--json")
            check(f"--where accepts the parser error form {form!r}",
                  r.returncode == 0 and json.loads(r.stdout).get("monolith_line") == 1234)
        for form in (f'#line {probe.bare + 1} "{Path(A.MONOLITH_REL).name}"', f"{Path(A.MONOLITH_REL).name}:{probe.bare + 1}"):
            r = cli("--where", form, "--json")
            check(f"--where accepts {form.split()[0] if form.startswith('#') else 'yaml:N'}",
                  r.returncode == 0 and json.loads(r.stdout).get("monolith_line") == probe.bare + 1)
        r = cli("--where", "not a location")
        check("--where refuses an uninterpretable argument (exit 2)", r.returncode == 2)
        shared = [c for c in amap.data.get("cross_area", []) if re.fullmatch(r"[A-Za-z0-9_]+", str(c.get("id", "")))]
        check("the map's cross_area list names at least three plain shared ids", len(shared) >= 3, str(len(shared)))
        defs = A.definitions(layout)
        for c in shared:
            t0 = time.perf_counter()
            r = cli("--lookup", c["id"], "--json")
            timings[f"--lookup {c['id'][:18]}"] = time.perf_counter() - t0
            res = json.loads(r.stdout) if r.returncode == 0 else {}
            owner_ok = c["id"] in defs and bool(res.get("defined")) and res["defined"]["area"] == c.get("owner")
            check(f"--lookup {c['id']}: owner {c.get('owner')} matches the map and other areas use it",
                  bool(res) and owner_ok and bool(res.get("cross_area")), json.dumps(res)[:300])
        t0 = time.perf_counter()
        r = cli("--xref", "--json")
        timings["--xref"] = time.perf_counter() - t0
        xr = {x["id"]: x for x in json.loads(r.stdout)} if r.returncode == 0 else {}
        listed = [c["id"] for c in shared if c["id"] in defs]
        check("--xref lists every map cross_area id that is defined as an item",
              listed and all(i in xr for i in listed), str([i for i in listed if i not in xr]))
        r = cli("--lookup", "no_such_id_anywhere_xyz")
        check("--lookup of an unknown id is refused (exit 2)", r.returncode == 2)
        mutated = A.parse_layout(mono.text.replace(probe_text := layout.text_of(probe.start, probe.end),
                                                   probe_text.replace("\n", "\n    # s2a probe\n", 1), 1))
        A.apply_area_map(mutated, amap)
        rows = A.diff_items(layout, mutated)
        check("diff_items reports exactly the one changed item with its area",
              len(rows) == 1 and rows[0]["change"] == "changed" and rows[0]["item"] == probe.ident
              and rows[0]["area"] == probe.area, str(rows)[:300])
        # a firmware PR the map does not cover yet: navigation degrades to core labels with a warning, never refuses
        lines_ = mono.text.split("\n")
        gk = lines_.index("globals:")
        mut = "\n".join(lines_[:gk + 1] + ["  - id: s2a_probe_new_global", "    type: int", "    initial_value: '0'"]
                         + lines_[gk + 1:])
        mp2 = tmp / "mono_new_item.yaml"
        mp2.write_bytes(mut.encode("utf-8"))
        r = cli("--diff-regions", "HEAD", "--monolith", str(mp2), "--json")
        rows_m = json.loads(r.stdout) if r.returncode == 0 else []
        check("--diff-regions HEAD on a monolith with one new item (not yet in the map) exits 0, reports exactly that "
              "added item and warns", r.returncode == 0 and [(x["change"], x["item"]) for x in rows_m]
              == [("added", "id:s2a_probe_new_global")] and "labelled core" in r.stderr, (r.stderr + r.stdout)[-300:])
        r = cli("--where", str(gk + 2), "--monolith", str(mp2), "--json")
        check("--where on that monolith still answers (area core, with a warning) instead of refusing",
              r.returncode == 0 and json.loads(r.stdout).get("item") == "id:s2a_probe_new_global"
              and "does not cover" in r.stderr, (r.stderr + r.stdout)[-300:])
        r = cli("--validate-map", "--monolith", str(mp2))
        check("--validate-map on that monolith is refused (exit 2): the map must be updated", r.returncode == 2)
        r = cli("--diff-regions", "HEAD", "--head", "HEAD")
        check("--diff-regions HEAD --head HEAD reports no change", r.returncode == 0 and "no item changed" in r.stdout)
        print("  info  CLI timings (s, incl. interpreter start): " + ", ".join(f"{k} {v:.2f}" for k, v in timings.items()))

        print("[7] map rules")

        def map_variant(fn) -> int:
            data = yaml.safe_load(AREAS.read_text(encoding="utf-8"))
            fn(data)
            p = tmp / f"map_{len(list(tmp.glob('map_*')))}.yaml"
            p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            return cli("--validate-map", "--areas-file", str(p)).returncode

        check("control: --validate-map on the committed map exits 0", cli("--validate-map").returncode == 0)
        check("a wrong run count is refused", map_variant(lambda d: d["runs"][0].update(n=d["runs"][0]["n"] + 1)) == 2)
        check("a wrong first anchor is refused", map_variant(lambda d: d["runs"][1].update(first="no_such_item")) == 2)
        check("an unknown area is refused", map_variant(lambda d: d["runs"][0].update(area="nowhere")) == 2)
        sec0 = amap.data["runs"][0]["section"]
        check("a section without runs is refused",
              map_variant(lambda d: d.update(runs=[r for r in d["runs"] if r["section"] != sec0])) == 2)
        r_warn = map_variant(lambda d: d.update(monolith_sha256_lf="0" * 64))
        data = yaml.safe_load(AREAS.read_text(encoding="utf-8"))
        data["monolith_sha256_lf"] = "0" * 64
        p = tmp / "map_sha.yaml"
        p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        r_strict = cli("--validate-map", "--areas-file", str(p), "--strict-map").returncode
        check("a reviewed-against sha that differs warns (exit 0) and fails with --strict-map (exit 2)",
              r_warn == 0 and r_strict == 2)

        print("[8] safety")
        bad = ast_violations(TOOL.read_text(encoding="utf-8"), ALLOWED_IMPORTS, WRITE_ATTRS)
        check("AST: allow-listed imports (no from-import or alias of os/subprocess); the only subprocess is `git -C <root> "
              "cat-file blob`; no eval/exec/shell; every file write/mkdir sits in the CLI handler _run (after the path "
              "guard)", not bad, str(bad))
        check("AST scan negative control: an aliased Popen, a from-import of os.system and a stray write are each flagged",
              len(ast_violations("import subprocess as sp\nfrom os import system\nsp.Popen(['x'])\n"
                                 "def f(p):\n    p.write_bytes(b'')\n", ALLOWED_IMPORTS, WRITE_ATTRS)) >= 3)
        for p in (TOOL, AREAS, Path(__file__)):
            t = p.read_text(encoding="utf-8")
            check(f"{p.relative_to(ROOT).as_posix()} spells neither the FB-A includer pattern nor the failback-shadow token",
                  not FBA_ANY_RE.search(t) and FBS_TOKEN not in t)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("[9] untouched")
    fw_after = tracked_firmware()
    check("the repository's firmware/ files are byte-identical before and after the suite", fw_before == fw_after)
    check("no stray output was left in the repository",
          not (ROOT / "dist" / "s2a_should_not_exist").exists() and not (ROOT / "tools" / "s2a_manifest.txt").exists())

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("\nAll firmware-assembly checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
