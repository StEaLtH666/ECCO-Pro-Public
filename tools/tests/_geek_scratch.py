"""Shared helpers of the Geek Mode suites (tools/tests/test_geek_mode_*.py): a tiny check() harness, running the tools as the CI
does, and a scratch copy of the parts of the repository the coverage tool READS, so a mutation (an undeclared attribute added to
the contract, a new automation in a package) can be tried without touching the real tree. Not a suite itself (no test_ prefix)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
FAILURES: list[str] = []
PY = [sys.executable, "-I", "-B", "-X", "utf8"]

# what tools/geek_mode_coverage.py and tools/gen_geek_fixtures.py read (repo-relative; a trailing / is a directory, *.py only)
# (review round 5: the coverage tool also reads every OTHER YAML file under home-assistant/, but only to refuse an ecco_intel_ data point defined in one: a scratch repository
# needs none of them, and a test that wants one writes it itself, or copies the whole tree as test_geek_mode_ledger.py block [7] does)
READ_SET = (
    "intelligence/", "ecco_core/", "custom_components/ecco_intelligence/", "home-assistant/packages/ecco_intelligence.yaml",
    "home-assistant/packages/ecco_intelligence_prefs.yaml", "home-assistant/packages/ecco_intelligence_dashboard.yaml",
    "home-assistant/dashboards/ecco_intelligence.yaml", "frontend/ecco-intelligence-card/ecco-intelligence-card.js",
)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def finish() -> None:
    print("")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("all checks passed")
    sys.exit(0)


def run_tool(script: str, *args: str, timeout: int = 300) -> tuple[int, str]:
    """Run a tool exactly as the instructions say (python -I -B -X utf8 <script> ...), from the repository root."""
    p = subprocess.run(PY + [str(TOOLS / script), *args], cwd=str(ROOT), capture_output=True, timeout=timeout,
                       env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


def scratch_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="geek_mode_scratch_"))


def copy_read_set(dest: Path) -> Path:
    """A scratch repository holding only what the tools read (the .py of the python packages, the YAML, the card). Never the tests
    of the packages except the contract fixture builders."""
    for rel in READ_SET:
        src = ROOT / rel
        if rel.endswith("/"):
            for p in src.rglob("*.py"):
                r = p.relative_to(ROOT)
                if "tests" in r.parts and r.name != "_gen_contract_fixtures.py":
                    continue
                if "__pycache__" in r.parts:
                    continue
                (dest / r).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dest / r)
        else:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest / rel)
    return dest


def copy_outputs(dest: Path) -> Path:
    """A scratch out-root holding the committed generated files (catalogue, ledger, live shape, fixtures, ledger Markdown)."""
    for rel in ("frontend/ecco-mode-shell/catalogue", "frontend/ecco-mode-shell/test/fixtures", "docs/product-ui"):
        shutil.copytree(ROOT / rel, dest / rel, dirs_exist_ok=True)
    return dest


def patch_file(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) < 1:
        raise AssertionError(f"patch target not found in {path.name}: {old[:60]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def cleanup(*dirs: Path) -> None:
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
