#!/usr/bin/env python3
"""Build the ECCO Intelligence SHADOW Home Assistant integration kit from the working tree (offline, no git, no network).

    python tools/build_ha_integration.py --out <abs-dir> [--git-sha S]          (the frozen command line)

Writes, under <out>:

    custom_components/ecco_intelligence/            the integration sources (no tests, no README) plus _vendor/
    custom_components/ecco_intelligence/_vendor/    the AST import closure (module level AND function level) of
                                                    intelligence.shadow_cycle, intelligence.scorecard, intelligence.history
                                                    and ecco_core.bridge, plus the package __init__ files on the path
    custom_components/ecco_intelligence/VENDOR_MANIFEST.json   (a copy, read by the integration's start-up self-test)
    VENDOR_MANIFEST.json                            per module: source path, sha256 of the source (LF), output path and
                                                    sha256; per integration file the same; the git sha when given
    SHA256SUMS                                      every file written, sha256sum format, sorted

Every absolute `intelligence.` / `ecco_core.` import, at any depth (function-level imports included), is rewritten to a
package-relative import, in the vendored modules and in the integration files alike, so nothing is ever put on Home
Assistant's global sys.path. Only import statements change; every other byte of a vendored module is kept (line endings are
normalised to LF). The output is byte-deterministic: two builds of one tree are identical.

Fail closed (exit 1, nothing written into an existing tree): an --out inside the repository, an --out that exists and is not
an empty directory, an unexpected file in the integration directory, a symlink, an unresolvable import, a vendor closure that
would reach ecco_autonomy, ecco_core.authority / ecco_core.capability, tests, tools, prototypes or profiles, or an import form
the rewrite cannot express. Nothing generated is ever written into the repository.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG_REL = "custom_components/ecco_intelligence"
SRC_PKG = REPO / "custom_components" / "ecco_intelligence"
ROOT_MODULES = ("intelligence.shadow_cycle", "intelligence.scorecard", "intelligence.history", "ecco_core.bridge")
VENDOR_TOPS = ("intelligence", "ecco_core")
NEVER_VENDOR_MODULES = frozenset({"ecco_core.authority", "ecco_core.capability"})
NEVER_VENDOR_PARTS = frozenset({"tests", "tools", "prototypes", "profiles"})
# what the integration directory may hold besides tests/ and README.md (anything else refuses the build)
SOURCE_SUFFIXES = (".py", ".json")
EXCLUDED_TOP = frozenset({"tests", "README.md", "__pycache__", "_vendor"})
MANIFEST_SCHEMA = "ecco-intel-vendor-manifest/1"
GIT_SHA_RE = re.compile(r"[0-9a-f]{7,40}")
FROM_RE = re.compile(r"from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import\b")


class BuildError(Exception):
    """The build cannot be proven safe or faithful: nothing is produced."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lf_text(path: Path) -> str:
    """The file as UTF-8 text with LF line endings (what git stores), refusing a symlink or a non-UTF-8 file."""
    if path.is_symlink():
        raise BuildError(f"{path.relative_to(REPO).as_posix()} is a symlink")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BuildError(f"{path.relative_to(REPO).as_posix()} is not UTF-8: {exc}") from None
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------------------------------------------------------------
# the vendor closure
# ---------------------------------------------------------------------------------------------------------------------

def module_file(mod: str) -> Path | None:
    p = REPO.joinpath(*mod.split("."))
    if (p / "__init__.py").is_file():
        return p / "__init__.py"
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py")
    return None


def _package_of(mod: str, path: Path) -> str:
    return mod if path.name == "__init__.py" else mod.rpartition(".")[0]


def repo_imports(mod: str, path: Path, tree: ast.AST) -> set[str]:
    """Every repository module (intelligence / ecco_core / ecco_autonomy) this module imports, at ANY depth."""
    out: set[str] = set()
    package = _package_of(mod, path)

    def add(target: str, names: tuple[str, ...]) -> None:
        top = target.split(".")[0]
        if top == "ecco_autonomy":
            raise BuildError(f"{mod} imports {target}: ecco_autonomy is never vendored")
        if top not in VENDOR_TOPS:
            return
        if module_file(target) is None:
            raise BuildError(f"{mod}: cannot resolve the import of {target}")
        out.add(target)
        for n in names:
            if n != "*" and module_file(f"{target}.{n}") is not None:
                out.add(f"{target}.{n}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                add(a.name, ())
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".") if package else []
                if node.level > len(parts):
                    raise BuildError(f"{mod}: a relative import climbs out of its package")
                base = parts[: len(parts) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            add(target, tuple(a.name for a in node.names))
    return out


def vendor_closure(roots: tuple[str, ...] = ROOT_MODULES) -> dict[str, Path]:
    """{module: source file} for the closure of `roots`, plus every package __init__ on the path."""
    seen: dict[str, Path] = {}
    todo = list(roots)
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        path = module_file(mod)
        if path is None:
            raise BuildError(f"cannot resolve the module {mod}")
        seen[mod] = path
        parts = mod.split(".")
        for i in range(1, len(parts)):                    # the packages on the path
            pkg = ".".join(parts[:i])
            if pkg not in seen:
                todo.append(pkg)
        tree = ast.parse(lf_text(path), filename=str(path))
        todo.extend(sorted(repo_imports(mod, path, tree) - set(seen)))
    for mod in seen:
        parts = mod.split(".")
        if mod in NEVER_VENDOR_MODULES or parts[0] not in VENDOR_TOPS or NEVER_VENDOR_PARTS & set(parts):
            raise BuildError(f"the vendor closure reaches {mod}, which is never vendored")
    return dict(sorted(seen.items()))


# ---------------------------------------------------------------------------------------------------------------------
# the import rewrite
# ---------------------------------------------------------------------------------------------------------------------

def _offsets(text: str) -> list[int]:
    starts, pos = [0], 0
    for line in text.split("\n")[:-1]:
        pos += len(line) + 1
        starts.append(pos)
    return starts


def rewrite_imports(text: str, depth: int, prefix: str, label: str) -> tuple[str, int]:
    """Rewrite every absolute intelligence / ecco_core import in `text` (any depth) to a relative one.

    `depth` is the number of leading dots that reach the directory holding `prefix` (the _vendor root for a vendored module,
    the integration package for an integration file); `prefix` is "" for a vendored module and "_vendor." for an integration
    file. Returns (new text, number of rewritten statements)."""
    tree = ast.parse(text, filename=label)
    starts = _offsets(text)
    edits: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] in VENDOR_TOPS:
            a = starts[node.lineno - 1] + node.col_offset
            b = starts[node.end_lineno - 1] + node.end_col_offset
            seg = text[a:b]
            m = FROM_RE.match(seg)
            if m is None or m.group(1) != node.module:
                raise BuildError(f"{label}:{node.lineno}: cannot rewrite this import form")
            edits.append((a, b, f"from {'.' * depth}{prefix}{node.module} import{seg[m.end():]}"))
        elif isinstance(node, ast.Import) and any(al.name.split(".")[0] in VENDOR_TOPS for al in node.names):
            al = node.names[0]
            if len(node.names) != 1 or al.asname is None or "." not in al.name:
                raise BuildError(f"{label}:{node.lineno}: write 'from <package> import <module> [as x]' for a repository "
                                 "import (a bare 'import intelligence...' cannot be made relative)")
            a = starts[node.lineno - 1] + node.col_offset
            b = starts[node.end_lineno - 1] + node.end_col_offset
            head, _dot, tail = al.name.rpartition(".")
            edits.append((a, b, f"from {'.' * depth}{prefix}{head} import {tail} as {al.asname}"))
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    after = ast.parse(text, filename=label)
    left = [n.lineno for n in ast.walk(after)
            if (isinstance(n, ast.ImportFrom) and n.level == 0 and (n.module or "").split(".")[0] in VENDOR_TOPS)
            or (isinstance(n, ast.Import) and any(x.name.split(".")[0] in VENDOR_TOPS for x in n.names))]
    count = lambda t: sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(t))  # noqa: E731
    if left or count(after) != count(tree):
        raise BuildError(f"{label}: the import rewrite is incomplete (lines {left})")
    return text, len(edits)


# ---------------------------------------------------------------------------------------------------------------------
# the integration sources
# ---------------------------------------------------------------------------------------------------------------------

def integration_sources() -> list[Path]:
    """The files of custom_components/ecco_intelligence that go into the kit: everything except tests/, README.md,
    caches and _vendor; any other kind of file refuses the build."""
    if not SRC_PKG.is_dir():
        raise BuildError(f"{PKG_REL} does not exist")
    out = []
    for dirpath, dirnames, filenames in os.walk(SRC_PKG):
        d = Path(dirpath)
        rel_dir = d.relative_to(SRC_PKG)
        for name in list(dirnames):
            if (d / name).is_symlink():
                raise BuildError(f"{(d / name).relative_to(REPO).as_posix()} is a symlink")
            if name == "__pycache__" or (rel_dir == Path(".") and name in EXCLUDED_TOP):
                dirnames.remove(name)
        dirnames.sort()
        for name in sorted(filenames):
            p = d / name
            if rel_dir == Path(".") and name in EXCLUDED_TOP:
                continue
            if p.suffix == ".pyc":
                continue
            if p.is_symlink() or p.suffix not in SOURCE_SUFFIXES:
                raise BuildError(f"unexpected file in the integration: {p.relative_to(REPO).as_posix()}")
            out.append(p)
    if not any(p.name == "manifest.json" and p.parent == SRC_PKG for p in out):
        raise BuildError(f"{PKG_REL}/manifest.json is missing")
    return sorted(out, key=lambda p: p.relative_to(SRC_PKG).as_posix())


# ---------------------------------------------------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------------------------------------------------

def check_out(out: Path) -> Path:
    if not out.is_absolute():
        raise BuildError("--out must be an absolute directory")
    res = Path(os.path.realpath(out))
    repo = Path(os.path.realpath(REPO))
    if res == repo or repo in res.parents:
        raise BuildError("--out must be outside the repository (nothing generated is ever written into it)")
    if res.exists() and (not res.is_dir() or any(res.iterdir())):
        raise BuildError("--out must not exist yet or be an empty directory (the build never deletes anything)")
    return res


def plan(git_sha: str | None) -> tuple[dict[str, bytes], dict]:
    """{out-relative path: bytes} for every file of the kit, and the vendor manifest."""
    files: dict[str, bytes] = {}
    modules = []
    for mod, path in vendor_closure().items():
        rel = path.relative_to(REPO).as_posix()
        src = lf_text(path)
        parts = rel.split("/")
        new, n = rewrite_imports(src, len(parts), "", rel)
        out_rel = f"_vendor/{rel}"
        data = new.encode("utf-8")
        files[f"{PKG_REL}/{out_rel}"] = data
        modules.append({"module": mod, "source": rel, "source_sha256_lf": sha256(src.encode("utf-8")), "output": out_rel,
                        "output_sha256": sha256(data), "rewritten_imports": n})
    files[f"{PKG_REL}/_vendor/__init__.py"] = (
        b'"""Generated by tools/build_ha_integration.py: the vendored, import-rewritten Intelligence engine (SHADOW only).\n'
        b'Never edited by hand and never committed; see VENDOR_MANIFEST.json."""\n')
    integration = []
    vendored = {m["module"] for m in modules}
    for p in integration_sources():
        rel = p.relative_to(SRC_PKG).as_posix()
        if p.suffix == ".py":
            src = lf_text(p)
            needed = repo_imports(f"custom_components.ecco_intelligence.{rel[:-3].replace('/', '.')}", p, ast.parse(src))
            missing = sorted(needed - vendored)
            if missing:
                raise BuildError(f"{PKG_REL}/{rel} imports {missing[0]}, which is not in the vendor closure of "
                                 f"{', '.join(ROOT_MODULES)}")
            new, n = rewrite_imports(src, len(rel.split("/")), "_vendor.", f"{PKG_REL}/{rel}")
            data = new.encode("utf-8")
        else:
            src = lf_text(p)
            json.loads(src)                                   # a malformed JSON file refuses the build
            data, n = src.encode("utf-8"), 0
        files[f"{PKG_REL}/{rel}"] = data
        integration.append({"path": rel, "source_sha256_lf": sha256(src.encode("utf-8")), "output_sha256": sha256(data),
                            "rewritten_imports": n})
    integration.append({"path": "_vendor/__init__.py", "source_sha256_lf": None,
                        "output_sha256": sha256(files[f"{PKG_REL}/_vendor/__init__.py"]), "rewritten_imports": 0})
    manifest = {"schema": MANIFEST_SCHEMA, "package": PKG_REL, "git_sha": git_sha, "roots": list(ROOT_MODULES),
                "modules": modules, "integration_files": sorted(integration, key=lambda r: r["path"]),
                "note": "SHADOW only; install only from a kit whose SHA256SUMS verifies; nothing here is deployed"}
    blob = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    files[f"{PKG_REL}/VENDOR_MANIFEST.json"] = blob
    files["VENDOR_MANIFEST.json"] = blob
    return dict(sorted(files.items())), manifest


def write(out: Path, files: dict[str, bytes]) -> str:
    for rel, data in files.items():
        p = out.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    sums = "".join(f"{sha256(files[rel])}  {rel}\n" for rel in sorted(files))
    with open(out / "SHA256SUMS", "wb") as fh:
        fh.write(sums.encode("utf-8"))
    return sha256(sums.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="absolute output directory outside the repository (new or empty)")
    ap.add_argument("--git-sha", default=None, help="the commit the tree was built from (recorded only)")
    args = ap.parse_args(argv)
    try:
        if args.git_sha is not None and not GIT_SHA_RE.fullmatch(args.git_sha):
            raise BuildError("--git-sha must be 7-40 lower-case hex digits")
        out = check_out(Path(args.out))
        files, manifest = plan(args.git_sha)
        out.mkdir(parents=True, exist_ok=True)
        sums_sha = write(out, files)
    except (BuildError, SyntaxError, ValueError, OSError) as exc:
        print(f"build_ha_integration: REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"built {PKG_REL} with {len(manifest['modules'])} vendored modules and {len(manifest['integration_files'])} "
          f"integration files; {len(files)} files; SHA256SUMS sha256 {sums_sha}")
    print("status: install kit staged, PENDING DP-4 (nothing is installed or deployed by this tool)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
