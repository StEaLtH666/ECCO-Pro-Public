#!/usr/bin/env python3
"""Regression suite: tools/run_offline_tests.py (the CI test runner) fails closed and never silently runs nothing.

Covers the roots file (missing / empty / comment-only / absolute / backslash / '..' / drive / odd characters / duplicate /
nested / not a directory / symlinked), roots with no tests, `--root` naming an unlisted root, a run in which an early suite
fails or times out (later suites must still run, exit 1), and the real repository's own roots. Throw-away directories only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import run_offline_tests as rot  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


PASS_SUITE = "import sys\nprint('hello')\nsys.exit(0)\n"
FAIL_SUITE = "import sys\nprint('BOOM-OUTPUT')\nsys.exit(3)\n"
HANG_SUITE = "import time\ntime.sleep(60)\n"


class Tree:
    def __init__(self, roots_text: str | None, files: dict[str, str] | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve()
        (self.repo / "tools").mkdir()
        if roots_text is not None:
            (self.repo / "tools" / "offline_test_roots.txt").write_text(roots_text, encoding="utf-8", newline="")
        for rel, text in (files or {}).items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        (self.repo / "tools" / "run_offline_tests.py").write_text((ROOT / "tools" / "run_offline_tests.py").read_text(encoding="utf-8"), encoding="utf-8")

    def cli(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(self.repo / "tools" / "run_offline_tests.py"), *args], cwd=self.repo,
                              capture_output=True, text=True, timeout=timeout)

    def close(self) -> None:
        self.tmp.cleanup()


def load_error(roots_text: str | None, files: dict[str, str] | None = None) -> str | None:
    t = Tree(roots_text, files)
    try:
        rot.load_roots(t.repo)
        return None
    except rot.RootsError as exc:
        return str(exc)
    finally:
        t.close()


GOOD = {"a/tests/test_one.py": PASS_SUITE, "a/tests/sub/test_two.py": PASS_SUITE, "a/tests/helper.py": "x = 1\n", "b/test_three.py": PASS_SUITE}

# ---------------------------------------------------------------------------
print("[1] The roots file fails closed")
# ---------------------------------------------------------------------------
check("missing roots file", load_error(None, GOOD) is not None)
check("empty roots file", load_error("", GOOD) is not None)
check("comment/blank-only roots file", load_error("# nothing\n\n   \n# more\n", GOOD) is not None)
for label, line in [("absolute path", "/etc"), ("Windows drive", "C:/x"), ("backslash", "a\\tests"), ("'..' component", "a/../b"),
                    ("leading '..'", "../a"), ("'.' component", "./a"), ("trailing slash", "a/tests/"), ("shell metacharacters", "a/tests; rm -rf x"),
                    ("command substitution", "$(id)"), ("space", "a tests"), ("leading dash", "-rf"), ("glob", "a/*"), ("double slash", "a//tests")]:
    check(f"bad root rejected: {label}", load_error(line + "\n", GOOD) is not None, line)
check("duplicate root rejected", load_error("a/tests\na/tests\n", GOOD) is not None)
check("nested roots rejected (suites would run twice)", load_error("a\na/tests\n", GOOD) is not None)
check("nested roots rejected in the other order", load_error("a/tests\na\n", GOOD) is not None)
check("sibling roots sharing a name prefix are NOT nested", load_error("a/tests\na/tests2\n", {**GOOD, "a/tests2/test_x.py": PASS_SUITE}) is None)
check("root that does not exist", load_error("nope\n", GOOD) is not None)
check("root that is a file", load_error("a/tests/helper.py\n", GOOD) is not None)

t = Tree("# comment\r\n\r\na/tests\r\n  b  \r\n", GOOD)
try:
    check("CRLF line endings, comments, blank lines and padding are accepted", rot.load_roots(t.repo) == ["a/tests", "b"], str(rot.load_roots(t.repo)))
finally:
    t.close()

LINKS = True
t = Tree("link\n", GOOD)
try:
    target = t.repo / "b"
    link = t.repo / "link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        LINKS = False
        if os.name == "nt":
            LINKS = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0
    if LINKS:
        try:
            rot.load_roots(t.repo)
            check("a symlinked/junctioned root is rejected", False)
        except rot.RootsError:
            check("a symlinked/junctioned root is rejected", True)
    else:
        print("  SKIP  no symlink/junction privilege here; the Linux CI runner exercises this case")
        if os.name == "posix":
            check("symlinks can be created on this POSIX host", False)
finally:
    t.close()

# ---------------------------------------------------------------------------
print("[2] Discovery: only test_*.py, sorted, recursive; a root with no tests is an error")
# ---------------------------------------------------------------------------
t = Tree("a/tests\nb\n", GOOD)
try:
    check("discovers test_*.py recursively, sorted, repo-relative POSIX, ignoring helpers",
          rot.discover("a/tests", t.repo) == ["a/tests/sub/test_two.py", "a/tests/test_one.py"], str(rot.discover("a/tests", t.repo)))
finally:
    t.close()
t = Tree("empty\n", {"empty/readme.txt": "x", "empty/helper.py": "x=1\n"})
try:
    try:
        rot.discover("empty", t.repo)
        check("a root containing no test_*.py is an error", False)
    except rot.RootsError:
        check("a root containing no test_*.py is an error", True)
    p = t.cli("--root", "empty")
    check("CLI --root on a root with no tests exits 2 (not 0)", p.returncode == 2 and "no test_*.py" in p.stderr, f"{p.returncode} {p.stderr!r}")
    p = t.cli("--list-roots-json")
    check("CLI --list-roots-json also refuses a root with no tests (no empty CI matrix leg)", p.returncode == 2, f"{p.returncode}")
finally:
    t.close()

# ---------------------------------------------------------------------------
print("[3] CLI behaviour")
# ---------------------------------------------------------------------------
t = Tree("a/tests\nb\n", GOOD)
try:
    p = t.cli("--list-roots-json")
    check("--list-roots-json prints the roots as a JSON array of strings", p.returncode == 0 and json.loads(p.stdout) == ["a/tests", "b"], p.stdout)
    p = t.cli("--root", "c")
    check("--root naming an UNLISTED root exits 2", p.returncode == 2 and "not listed" in p.stderr, p.stderr)
    p = t.cli("--root", "../etc")
    check("--root '../etc' exits 2", p.returncode == 2)
    p = t.cli("--root", "b")
    check("--root b runs only b's suites and exits 0", p.returncode == 0 and "b/test_three.py" in p.stdout and "a/tests" not in p.stdout.split("Running", 1)[1].split("\n", 1)[1], p.stdout)
    p = t.cli("--all")
    check("--all runs every root's suites (3) and exits 0", p.returncode == 0 and "3/3 passed" in p.stdout, p.stdout)
finally:
    t.close()

t = Tree("s\n", {"s/test_a_fails.py": FAIL_SUITE, "s/test_b_passes.py": PASS_SUITE, "s/test_c_hangs.py": HANG_SUITE, "s/test_d_passes.py": PASS_SUITE})
try:
    p = t.cli("--root", "s", "--timeout", "3", "--parallel", "2", timeout=120)
    out = p.stdout
    check("a failing suite and a timing-out suite give exit 1", p.returncode == 1, f"{p.returncode} {out}")
    check("every suite still ran after the first failure (2 passed of 4)", "2/4 passed" in out and "ok" in out and "test_d_passes.py" in out, out)
    check("the failing suite's output is shown", "BOOM-OUTPUT" in out and "exit 3" in out, out)
    check("a hung suite is reported as TIMEOUT (and does not hang the runner)", "TIMEOUT" in out, out)
finally:
    t.close()

# ---------------------------------------------------------------------------
print("[4] The real repository")
# ---------------------------------------------------------------------------
roots = rot.load_roots(ROOT)
check("the real roots file loads", bool(roots), str(roots))
# PUBLIC-EXPORT staging: the core import precedes the Intelligence import; the Intelligence commit restores this check's
# "intelligence/tests" half (the public CI baseline as written).
check("the real roots include the tools suites", "tools/tests" in roots, str(roots))
counts = {r: len(rot.discover(r, ROOT)) for r in roots}
check("every real root has at least one suite", all(c >= 1 for c in counts.values()), str(counts))
check("this suite is discovered under the real tools/tests root", "tools/tests/test_run_offline_tests.py" in rot.discover("tools/tests", ROOT))
check("the real roots are valid CI-matrix strings", all(rot.ROOT_RE.match(r) for r in roots))

if FAILURES:
    print(f"\n{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f" - {f}")
    sys.exit(1)
print("\nAll run_offline_tests checks passed")
