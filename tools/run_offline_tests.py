#!/usr/bin/env python3
"""Discover and run the offline test suites listed in tools/offline_test_roots.txt. Standard library only.

    python tools/run_offline_tests.py --list-roots-json      # ["registry/tests", ...]  (CI matrix input)
    python tools/run_offline_tests.py --root registry/tests  # run every test_*.py under that ONE root
    python tools/run_offline_tests.py --all                  # run every root

A suite is one `test_*.py` file run as `python <file>` from the repository root and must exit 0.

Fail closed (exit 2, nothing run) when the roots file is missing/unreadable/empty, a root line is malformed
(absolute, backslash, drive colon, '..', odd characters), duplicated, nested inside another root, missing, a
symlink, or contains no test_*.py, or when --root names something the roots file does not list.
Every discovered suite is run to completion even if an earlier one fails; exit 1 if any failed or timed out.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS_FILE_REL = "tools/offline_test_roots.txt"
ROOT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


class RootsError(Exception):
    """The roots file or the tree it points at cannot be trusted; nothing may run."""


def _is_link(p: Path) -> bool:
    return p.is_symlink() or bool(getattr(os.path, "isjunction", lambda _p: False)(p))


def load_roots(repo: Path = REPO, roots_file: str = ROOTS_FILE_REL) -> list[str]:
    path = repo / roots_file
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RootsError(f"{roots_file} is missing or unreadable: {exc}") from exc
    roots: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not ROOT_RE.match(line) or line.endswith("/") or ".." in line.split("/") or "." in line.split("/") or "//" in line:
            raise RootsError(f"bad test root {line!r} in {roots_file}")
        if line in roots:
            raise RootsError(f"duplicate test root {line!r} in {roots_file}")
        d = repo / line
        if not d.is_dir():
            raise RootsError(f"test root {line!r} is not a directory")
        cur = repo
        for part in line.split("/"):
            cur = cur / part
            if _is_link(cur):
                raise RootsError(f"test root {line!r} passes through a symlink/junction ({part})")
        roots.append(line)
    if not roots:
        raise RootsError(f"{roots_file} lists no test roots")
    for a in roots:
        for b in roots:
            if a != b and (b + "/").startswith(a + "/"):
                raise RootsError(f"test root {b!r} is nested inside {a!r} (its suites would run twice)")
    return roots


def discover(root: str, repo: Path = REPO) -> list[str]:
    """Repo-relative POSIX paths of every test_*.py under `root`, sorted. Never follows links; none found is an error."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo / root, followlinks=False):
        for d in list(dirnames):
            if _is_link(Path(dirpath) / d):
                raise RootsError(f"{(Path(dirpath) / d).relative_to(repo).as_posix()} is a symlink/junction under {root}")
        for f in filenames:
            if f.startswith("test_") and f.endswith(".py"):
                p = Path(dirpath) / f
                if _is_link(p):
                    raise RootsError(f"{p.relative_to(repo).as_posix()} is a symlink")
                found.append(p.relative_to(repo).as_posix())
    if not found:
        raise RootsError(f"no test_*.py found under test root {root!r}")
    return sorted(found)


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)  # the suites spawn compilers; kill the whole group
        else:
            proc.kill()
    except OSError:
        pass


def run_one(test: str, timeout: int, repo: Path = REPO) -> tuple[str, int | str, float, str]:
    start = time.time()
    with tempfile.TemporaryFile() as out:  # a file, not a pipe: a surviving grandchild cannot wedge us after a kill
        proc = subprocess.Popen([sys.executable, test], cwd=repo, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=(os.name == "posix"))
        try:
            rc: int | str = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            proc.wait()
            rc = "TIMEOUT"
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    return test, rc, time.time() - start, text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-roots-json", action="store_true", help="print the validated roots as a JSON array and exit")
    mode.add_argument("--root", help="run the suites under this one root (must be listed in the roots file)")
    mode.add_argument("--all", action="store_true", help="run every root")
    ap.add_argument("--parallel", type=int, default=1, help="suites run at once (default 1; suites use temp dirs)")
    ap.add_argument("--timeout", type=int, default=5400, help="seconds allowed per suite (default 5400)")
    args = ap.parse_args(argv)
    if args.parallel < 1 or args.timeout < 1:
        ap.error("--parallel and --timeout must be >= 1")
    try:
        roots = load_roots()
        if args.list_roots_json:
            for r in roots:
                discover(r)  # a root with no tests must fail here too, before a CI matrix is built
            print(json.dumps(roots))
            return 0
        if args.root is not None:
            if args.root not in roots:
                raise RootsError(f"--root {args.root!r} is not listed in {ROOTS_FILE_REL}")
            roots = [args.root]
        tests = [t for r in roots for t in discover(r)]
    except RootsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Running {len(tests)} suite(s) under: {', '.join(roots)}", flush=True)
    results: list[tuple[str, int | str, float]] = []
    t0 = time.time()
    with ThreadPoolExecutor(args.parallel) as pool:
        for test, rc, secs, text in pool.map(lambda t: run_one(t, args.timeout), tests):
            print(f"{'ok  ' if rc == 0 else 'FAIL'} {secs:7.1f}s  {test}", flush=True)
            results.append((test, rc, secs))
            if rc != 0:
                print(f"::group::output of failing suite {test} (exit {rc})")
                print(text[-20000:])
                print("::endgroup::")
    failed = [r for r in results if r[1] != 0]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Offline suites ({', '.join(roots)}): {len(results) - len(failed)}/{len(results)} passed, "
                     f"wall {time.time() - t0:.0f}s\n\n| suite | result | seconds |\n|---|---|---|\n")
            for test, rc, secs in sorted(results, key=lambda r: -r[2]):
                fh.write(f"| `{test}` | {'ok' if rc == 0 else 'FAIL ' + str(rc)} | {secs:.0f} |\n")
    print(f"{len(results) - len(failed)}/{len(results)} passed in {time.time() - t0:.0f}s; "
          f"failed: {[r[0] for r in failed] or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
