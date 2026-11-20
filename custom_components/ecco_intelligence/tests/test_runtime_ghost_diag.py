#!/usr/bin/env python3
"""The Ghost's diagnostics block in the integration (Ghost, diagnostics-only): the wiring, proven in the live tree.

The wiring (coordinator, diagnostics, runtime/ghost_link.py, RuntimeStateStore.advice_rows) IS APPLIED to this tree; the patch it
came from, tests/ghost_diag_wiring.patch, stays UNCHANGED as the record of the wiring as it was first proven, and the live files
have moved on from it since (review fixes), so it no longer reverses byte for byte. The wiring made the integration import
intelligence.ghost_compare, so the kit's vendor roots (tools/build_ha_integration.py ROOT_MODULES) list it, and the two tests that
pin those roots or the runtime modules (test_runtime_build.py ROOTS, test_runtime_import_without_ha.py's module list) were re-pinned.

This suite:
  [1] the live tree: the wiring is detected (the patch reverses cleanly, or runtime/ghost_link.py is there) and the L2 scenarios run
      in the live tree. For a tree WITHOUT the wiring the older path remains: the patch is applied to a temporary copy, proven to
      apply cleanly, and the next two steps run on the copy;
  [2] FAIL-FIRST (the copy path only): on the unpatched copy the L2 scenarios fail (the download has no ghost block);
  [3] (the copy path only) on the patched copy: the untouched runtime boundary suite passes (no write, service call, state or bus
      write, network or process; the import rules, the vendored copy's rules), the build suite and the runtime-import suite pass with
      the patch's re-pins, and tests/_ghost_diag_l2.py passes: the block in the download (money with a verified tariff, NO MONEY,
      insufficient history, no advice, followed and not followed, config not decided, no cycle yet), the failure blocks, the size
      bound, redaction, no write and no twelfth entity, the time budget, the placeholder window, computed on request only, timing,
      an import-time fault of the Ghost code, the job kept only after a published result;
  [3b] the coordinator and the diagnostics import no Ghost code at import time (static);
  [3c] the documents and docstrings state the durable advice-log write and the sharing warning, and no longer claim "nothing written";
  [4] the live tree is unchanged by all of it (nothing here writes into the repository).
Plain script; exits 1 on any failure. Synthetic data only; no network.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


REPO = H.REPO
PATCH = TESTS / "ghost_diag_wiring.patch"
PREFIX = "ecco_intel_ghost_overlay_"
COPY = ("intelligence", "ecco_core", "custom_components", "docs/intelligence")
TOOL_FILES = ("build_ha_integration.py",)
GIT = shutil.which("git")


def git_apply(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([GIT, "apply", "-p1", "--whitespace=nowarn", *args, str(PATCH)], cwd=str(cwd), capture_output=True,
                          text=True, timeout=120)


def run(script: Path, cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(script)], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)


def fails(p: subprocess.CompletedProcess) -> list[str]:
    return [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip().startswith("FAIL")]


def tree_digest(root: Path) -> dict[str, str]:
    return {k: v for k, v in H.tree_hashes(root).items() if not k.startswith(("intelligence/tests/__pycache__",)) and "__pycache__" not in k}


def make_copy(dst: Path) -> Path:
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    for d in COPY:
        shutil.copytree(REPO / d, dst / d, ignore=ign)
    (dst / "tools").mkdir()
    for f in TOOL_FILES:
        shutil.copy2(REPO / "tools" / f, dst / "tools" / f)
    return dst


TEST_DIR = "custom_components/ecco_intelligence/tests"
check("git is available and the patch file exists", GIT is not None and PATCH.is_file(), str(PATCH))
root = H.mktemp(PREFIX)
live_before = tree_digest(REPO / "custom_components" / "ecco_intelligence")
try:
    if GIT is None or not PATCH.is_file():
        raise SystemExit(1)
    reverse = git_apply(REPO, "--check", "-R")
    # The wiring is APPLIED when the patch reverses cleanly on the live tree OR the live tree carries runtime/ghost_link.py (the file
    # the patch adds). After the review fixes the live files have moved on from the patch, which stays UNCHANGED as the record of the
    # wiring as it was proven, so it no longer reverses byte for byte. Every other check of this suite is unchanged.
    wired = (REPO / "custom_components" / "ecco_intelligence" / "runtime" / "ghost_link.py").is_file()
    already = reverse.returncode == 0 or wired
    print(f"== [1] the patch against the live tree ({'already applied' if already else 'not applied: the integration is not wired yet'})")
    if already:
        check("the wiring is applied to the live tree: the L2 scenarios run there", True)
        p = run(TESTS / "_ghost_diag_l2.py", REPO)
        check("the Ghost diagnostics L2 scenarios pass in the live tree", p.returncode == 0, (p.stdout + p.stderr)[-600:])
        print(p.stdout[-2500:])
    else:
        ov = make_copy(root / "ov")
        check("the patch applies cleanly to a temporary copy of the live tree", git_apply(ov, "--check").returncode == 0,
              git_apply(ov, "--check").stderr[-400:])
        print("== [2] fail-first: the L2 scenarios on the unpatched copy")
        old = run(ov / TEST_DIR / "_ghost_diag_l2.py", ov)
        check("on the unpatched copy the L2 scenarios FAIL (the download has no ghost block, so the integration is not wired)",
              old.returncode != 0 and ("ghost" in (old.stdout + old.stderr)), (old.stdout + old.stderr)[-500:])
        print("== [3] the patched copy")
        ap = git_apply(ov)
        check("the patch applies", ap.returncode == 0, ap.stderr[-400:])
        check("the patch adds runtime/ghost_link.py and the copy's coordinator and diagnostics use it",
              (ov / "custom_components" / "ecco_intelligence" / "runtime" / "ghost_link.py").is_file()
              and "ghost_link" in (ov / "custom_components" / "ecco_intelligence" / "coordinator.py").read_text(encoding="utf-8")
              and "ghost" in (ov / "custom_components" / "ecco_intelligence" / "diagnostics.py").read_text(encoding="utf-8"))
        bnd = run(ov / TEST_DIR / "test_runtime_boundaries.py", ov)
        check("the UNTOUCHED runtime boundary suite passes on the patched copy (no write path, no service call, no network or "
              "process, import and vendor rules)", bnd.returncode == 0 and not fails(bnd) and "all runtime boundary checks passed" in bnd.stdout,
              str(fails(bnd)[:3]))
        bld = run(ov / TEST_DIR / "test_runtime_build.py", ov)
        check("the build suite passes with the patch's re-pin of the vendor roots", bld.returncode == 0 and not fails(bld), str(fails(bld)[:3]))
        imp = run(ov / TEST_DIR / "test_runtime_import_without_ha.py", ov)
        check("the runtime import-without-Home-Assistant suite passes with the patch's module list", imp.returncode == 0 and not fails(imp),
              str(fails(imp)[:3]))
        l2 = run(ov / TEST_DIR / "_ghost_diag_l2.py", ov)
        check("the Ghost diagnostics L2 scenarios pass on the patched copy", l2.returncode == 0 and not fails(l2) and
              "all Ghost diagnostics L2 checks passed" in l2.stdout, str(fails(l2)[:5]) + (l2.stdout + l2.stderr)[-300:])
        npass = sum(1 for ln in l2.stdout.splitlines() if ln.strip().startswith("PASS"))
        print(f"  INFO  the L2 scenarios ran {npass} checks on the patched copy")
        for ln in l2.stdout.splitlines():
            if "INFO" in ln:
                print(ln)
    print("== [3b] import-time safety (G9): the coordinator and the diagnostics import no Ghost code at import time")
    import ast

    def import_names(path: Path) -> tuple[list[str], list[str]]:
        """(import-time imports, function-level imports) of a module, as 'module:name' strings (relative level as dots)."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top, deep = [], []

        def walk(node, in_func: bool) -> None:
            for ch in ast.iter_child_nodes(node):
                now_in = in_func or isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                if isinstance(ch, ast.Import):
                    (deep if in_func else top).extend(f":{a.name}" for a in ch.names)
                elif isinstance(ch, ast.ImportFrom):
                    (deep if in_func else top).extend(f"{'.' * ch.level}{ch.module or ''}:{a.name}" for a in ch.names)
                walk(ch, now_in)
        walk(tree, False)
        return top, deep
    pkg = REPO / "custom_components" / "ecco_intelligence"
    for fn in ("coordinator.py", "diagnostics.py"):
        top, deep = import_names(pkg / fn)
        check(f"{fn}: no import-time import of ghost_compare, ghost_link, ghost_feed or ghost",
              not [x for x in top if any(w in x for w in ("ghost_compare", "ghost_link", "ghost_feed", ":ghost", ".ghost"))], str(top))
    c_top, c_deep = import_names(pkg / "coordinator.py")
    check("non-vacuity: the coordinator still imports ghost_compare and ghost_link, lazily, inside async_ghost_diagnostics",
          any("ghost_compare" in x for x in c_deep) and any("ghost_link" in x for x in c_deep), str(c_deep))
    print("== [3c] the documents say what is written (G2) and what the block carries (G8)")

    def doc(rel: str) -> str:
        return (REPO / rel).read_text(encoding="utf-8")
    pkg_rel = "custom_components/ecco_intelligence"
    texts = {"intelligence/README.md": doc("intelligence/README.md"), "docs/intelligence/INTELLIGENCE_HA_RUNTIME.md":
             doc("docs/intelligence/INTELLIGENCE_HA_RUNTIME.md"), f"{pkg_rel}/runtime/ghost_link.py": doc(f"{pkg_rel}/runtime/ghost_link.py"),
             f"{pkg_rel}/diagnostics.py": doc(f"{pkg_rel}/diagnostics.py"), f"{pkg_rel}/runtime/store.py": doc(f"{pkg_rel}/runtime/store.py")}
    wrong = ("no new failure path", "does no extra work", "nothing written")
    check("no document or docstring of the Ghost wiring still says 'no new failure path', 'does no extra work' or 'nothing written' "
          "(the slot cycle writes the advice log)", not {k: [w for w in wrong if w in t.lower()] for k, t in texts.items()
                                                         if any(w in t.lower() for w in wrong)},
          str({k: [w for w in wrong if w in t.lower()] for k, t in texts.items() if any(w in t.lower() for w in wrong)}))
    for rel, words in (("intelligence/README.md", ("durable write", "52 rows a day", "400 days", "advice_write_failures", "roll back", "before sharing")),
                       ("docs/intelligence/INTELLIGENCE_HA_RUNTIME.md", ("durable write", "52 rows a day", "advice_write_failures", "roll back")),
                       (f"{pkg_rel}/runtime/ghost_link.py", ("advice log", "durable")),
                       (f"{pkg_rel}/diagnostics.py", ("site-derived", "before sharing")),
                       (f"{pkg_rel}/runtime/store.py", ("durable write", "52 a day"))):
        miss = [w for w in words if w not in texts[rel]]
        check(f"{rel} states the durable advice-log write, its size, its failure counter, the rollback and the sharing warning as relevant to it",
              not miss, str(miss))
    print("== [4] the live tree is unchanged")
    check("nothing in the live integration directory changed", tree_digest(REPO / "custom_components" / "ecco_intelligence") == live_before)
finally:
    H.rmtree_own(root, PREFIX)

check("the temporary directory is removed", not root.exists(), str(root))
print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in the Ghost diagnostics wiring suite:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all Ghost diagnostics wiring checks passed")
