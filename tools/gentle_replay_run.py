#!/usr/bin/env python3
"""One-command offline Gentle replay (read only): recorded nights in, a plain comparison out. No Home Assistant, no network, no write but --output.

    python tools/gentle_replay_run.py EVIDENCE_DIR [--window 00:30-05:30] [--target auto|N] [--buffer-min 60] [--calibrate loo] [--output FILE] [...]

It runs intelligence/tools/gentle_replay.py (reads the recorded history files, finds the cheap-window nights, measures what the battery did, builds the
questions for the advice and prints the report) and, in between, Node on frontend/ecco-plan-core/tools/adviseBatch.ts, which asks the one implementation of
the advice (frontend/ecco-plan-core/src/gentleAdvice.ts, a pure function that changes nothing) the questions. Every option of gentle_replay.py is accepted
(see its module text); `--node` names the Node executable (22.18 or newer).

This driver exists outside intelligence/ because the Intelligence tools may not start a process (the authority-separation gate): the only process started
here is Node, by an argument list (never a shell), with the questions on standard input and the answers on standard output.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from intelligence.tools import gentle_replay as gr  # noqa: E402

RUNNER = REPO / "frontend" / "ecco-plan-core" / "tools" / "adviseBatch.ts"


def node_backend(node: str = "node", runner: Path = RUNNER) -> gr.Backend:
    """The advice as the one implementation: Node runs adviseBatch.ts on the questions. A failed run or a failed answer is an error, never a guess."""
    exe = shutil.which(node)
    if exe is None:
        raise gr.ToolError(f"{node!r} was not found: the advice runs in Node (22.18 or newer)")
    try:
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, check=True).stdout.strip()
        major, minor = (int(x) for x in ver.lstrip("v").split(".")[:2])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise gr.ToolError(f"cannot run {exe}: {exc}") from exc
    if (major, minor) < (22, 6):
        raise gr.ToolError(f"Node {ver} is too old (type stripping needs 22.6 or newer, 22.18 or newer without a flag)")
    # type stripping is on by default from Node 22.18 and 23.6; before that it is behind a flag
    flags = ["--disable-warning=ExperimentalWarning"] if (major, minor) >= (22, 18) and not (major == 23 and minor < 6) else ["--experimental-strip-types", "--disable-warning=ExperimentalWarning"]

    def run(cases: list[dict]) -> list[dict]:
        proc = subprocess.run([exe, *flags, str(runner)], input=json.dumps({"cases": cases}), capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise gr.ToolError(f"the advice runner failed (exit {proc.returncode}): {proc.stderr.strip()[:300]}")
        try:
            results = json.loads(proc.stdout)["results"]
        except (ValueError, KeyError) as exc:
            raise gr.ToolError(f"the advice runner returned something that is not results: {proc.stdout[:200]!r}") from exc
        if len(results) != len(cases) or any("error" in r for r in results):
            bad = [r for r in results if "error" in r][:1]
            raise gr.ToolError(f"the advice runner failed on a case: {bad}")
        return results

    return run


def main(argv: list[str] | None = None) -> int:
    ap = gr.build_parser(driver=True)
    ap.add_argument("--node", default="node", help="the Node executable that runs the advice (default node)")
    args = ap.parse_args(argv)
    try:
        backend = node_backend(args.node)
    except gr.ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return gr.run(args, backend, "frontend/ecco-plan-core/src/gentleAdvice.ts via Node")


if __name__ == "__main__":
    sys.exit(main())
