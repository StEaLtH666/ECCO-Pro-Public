#!/usr/bin/env python3
"""The Ghost's diagnostics block in the integration (Ghost, diagnostics-only): the wiring, proven on a temporary copy.

The wiring is a patch, tests/ghost_diag_wiring.patch, NOT applied to the live tree: it makes the integration import
intelligence.ghost_compare, which the kit's vendor roots (tools/build_ha_integration.py ROOT_MODULES) do not list, and two pinned
tests list those roots or the runtime modules (test_runtime_build.py ROOTS, test_runtime_import_without_ha.py's module list), so
applying it is a re-pin only the owner may approve. The patch contains those re-pins (and the doc line), so the copy is consistent.

This suite:
  [1] the live tree: the patch applies cleanly to a temporary copy of it (and, if it is already applied to the live tree, the L2
      scenarios run there directly);
  [2] FAIL-FIRST: on the unpatched copy the L2 scenarios fail (the download has no ghost block);
  [3] on the patched copy: the untouched runtime boundary suite passes (no write, service call, state or bus write, network or
      process; the import rules, the vendored copy's rules), the build suite and the runtime-import suite pass with the patch's
      re-pins, and tests/_ghost_diag_l2.py passes: the block in the download (money with a verified tariff, NO MONEY, insufficient
      history, no advice, followed and not followed, config not decided, no cycle yet), the failure blocks, the size bound,
      redaction, no write and no twelfth entity, the time budget, the placeholder window, computed on request only, timing;
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
    # wiring as it was proven (910d975), so it no longer reverses byte for byte. Every other check of this suite is unchanged.
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
