"""Mutation score of the Gentle night planner's BEHAVIOURAL assertion suites (read only, offline).

Each single-line mutant of src/gentleNight.ts listed in test/support/gentleNightProbe.ts (MUTANTS) is applied to a private copy of the
package, and the assertion suites are run against it: test/gentleNight.test.ts, test/gentleNightSafety.test.ts,
test/gentleNightClosedLoop.test.ts and test/gentleNightGolden.test.ts. They import nothing from the probe or the golden, so a kill
here means a behavioural assertion failed (test/gentleNightMutants.test.ts, the golden-probe kill, is deliberately NOT run).

One Node process at a time (the test runner in-process, --test-isolation=none). Nothing in the repository is changed: the copy lives
in a temporary directory that is removed afterwards. Exit 0 when every mutant is killed, 1 when one survives, 2 on a set-up error.

Usage, from anywhere:
    python -I -B tools/night_mutation_score.py [--node "node"] [--only SUBSTRING] [--show-failures]
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
SUITES = [
    "test/gentleNight.test.ts",
    "test/gentleNightSafety.test.ts",
    "test/gentleNightClosedLoop.test.ts",
    "test/gentleNightGolden.test.ts",
]


def node_cmd(spec: str) -> list[str]:
    return shlex.split(spec, posix=True)


def load_mutants(node: list[str]) -> list[dict]:
    probe = (PKG / "test" / "support" / "gentleNightProbe.ts").as_uri()
    code = "const m = await import(" + json.dumps(probe) + "); console.log(JSON.stringify(m.MUTANTS));"
    out = subprocess.run(node + ["--input-type=module", "-e", code], capture_output=True, text=True, encoding="utf-8", check=False)
    if out.returncode != 0:
        raise RuntimeError("could not load the mutant list: " + out.stderr.strip()[-400:])
    lines = [line for line in out.stdout.splitlines() if line.startswith("[")]
    return json.loads(lines[-1])


def failing_tests(tap: str) -> list[str]:
    names = []
    for line in tap.splitlines():
        s = line.strip()
        if s.startswith("not ok ") and " - " in s:
            names.append(s.split(" - ", 1)[1])
    return names


def run_suites(node: list[str], work: Path) -> tuple[int, list[str]]:
    cmd = node + ["--test", "--test-concurrency=1", "--test-isolation=none", "--test-reporter=tap"] + SUITES
    out = subprocess.run(cmd, cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return out.returncode, failing_tests(out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--node", default="node", help='the Node command, e.g. "node" or a wrapper such as "bash /path/gnode.sh"')
    ap.add_argument("--only", default="", help="run only the mutants whose id contains this text")
    ap.add_argument("--show-failures", action="store_true", help="list the failing assertion tests of each killed mutant")
    args = ap.parse_args()
    node = node_cmd(args.node)
    try:
        mutants = [m for m in load_mutants(node) if args.only in m["id"]]
    except (RuntimeError, ValueError, IndexError) as exc:
        print("set-up error:", exc, file=sys.stderr)
        return 2
    source = (PKG / "src" / "gentleNight.ts").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="night-mutation-") as tmp:
        work = Path(tmp) / "pkg"
        shutil.copytree(PKG / "src", work / "src")
        shutil.copytree(PKG / "test", work / "test")
        shutil.copy2(PKG / "package.json", work / "package.json")
        target = work / "src" / "gentleNight.ts"
        code, failed = run_suites(node, work)
        if code != 0:
            print("set-up error: the assertion suites fail on the real source:", failed[:5], file=sys.stderr)
            return 2
        survivors = []
        for i, mu in enumerate(mutants, 1):
            if source.count(mu["from"]) != 1:
                print("set-up error: the anchor of", repr(mu["id"]), "does not occur exactly once", file=sys.stderr)
                return 2
            target.write_text(source.replace(mu["from"], mu["to"], 1), encoding="utf-8", newline="\n")
            code, failed = run_suites(node, work)
            killed = code != 0
            if not killed:
                survivors.append(mu["id"])
            mark = "killed  " if killed else "SURVIVED"
            print(f"{i:3d} {mark} {mu['id']}")
            if killed and args.show_failures:
                for name in failed[:3]:
                    print("            by:", name)
        target.write_text(source, encoding="utf-8", newline="\n")
    total = len(mutants)
    print(f"\nmutation score against the assertion suites: {total - len(survivors)} of {total} killed")
    for sid in survivors:
        print("  survived:", sid)
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main())
