#!/usr/bin/env python3
"""Static security policy for .github/workflows/*.yml (offline; needs PyYAML only).

    python tools/check_workflows.py [--require-sha-pins] [workflow.yml ...]   # default: every file in .github/workflows

This is the project's own guard for a PUBLIC repository where a pull request may carry arbitrary code. It does not
replace actionlint (syntax/expression typing); it enforces the security shape that actionlint does not:

  * events limited to pull_request, push (branch main only) and workflow_dispatch (no inputs);
    never pull_request_target, workflow_run, issue_comment, schedule, ...
  * top-level permissions exactly {contents: read}; job-level permissions never broader
  * every job: ubuntu-* GitHub-hosted literal runs-on (never self-hosted, never an expression), explicit
    timeout-minutes in 1..240, no continue-on-error, no environment, no container/services
  * only first-party `actions/*` actions, pinned to a version tag (or, with --require-sha-pins, a 40-hex commit SHA);
    no local actions, no docker://
  * every actions/checkout has persist-credentials: false
  * no secrets / GITHUB_TOKEN / github.token, and no `${{ ... }}` expression inside any `run:` script (pass values
    through env: instead, so event data can never become shell code)
  * no git push / git commit in scripts; upload-artifact retention-days <= 14
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EVENTS = {"pull_request", "push", "workflow_dispatch"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TAG_RE = re.compile(r"^v\d+(\.\d+){0,2}$")
MAX_TIMEOUT = 240
MAX_RETENTION = 14


def _events(on: object) -> dict:
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {e: None for e in on}
    if isinstance(on, dict):
        return on
    return {}


def check_workflow(text: str, name: str = "workflow", require_sha_pins: bool = False) -> list[str]:
    """Return a list of policy problems (empty = compliant)."""
    problems: list[str] = []

    def bad(msg: str) -> None:
        problems.append(f"{name}: {msg}")

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"{name}: does not parse as YAML: {exc}"]
    if not isinstance(doc, dict):
        return [f"{name}: top level is not a mapping"]

    on = doc.get("on", doc.get(True))  # PyYAML (YAML 1.1) reads the key `on` as boolean True
    events = _events(on)
    if not events:
        bad("no `on:` events")
    for ev, cfg in events.items():
        if ev not in ALLOWED_EVENTS:
            bad(f"event {ev!r} is not allowed (allowed: {sorted(ALLOWED_EVENTS)})")
        if ev == "push":
            branches = (cfg or {}).get("branches") if isinstance(cfg, dict) else None
            if branches != ["main"] or (isinstance(cfg, dict) and ("tags" in cfg or "branches-ignore" in cfg)):
                bad("push must be limited to `branches: [main]` (no tags, no other branches)")
        if ev == "workflow_dispatch" and isinstance(cfg, dict) and cfg.get("inputs"):
            bad("workflow_dispatch must not take inputs")

    if doc.get("permissions") != {"contents": "read"}:
        bad(f"top-level permissions must be exactly {{contents: read}}, got {doc.get('permissions')!r}")

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        bad("no jobs")
        return problems
    for jid, job in jobs.items():
        where = f"job {jid!r}"
        if not isinstance(job, dict):
            bad(f"{where} is not a mapping")
            continue
        perms = job.get("permissions")
        if perms is not None and perms not in ({}, {"contents": "read"}):
            bad(f"{where}: job-level permissions must be absent, {{}} or {{contents: read}}, got {perms!r}")
        runs_on = job.get("runs-on")
        if not (isinstance(runs_on, str) and re.fullmatch(r"ubuntu-[0-9.]+|ubuntu-latest", runs_on)):
            bad(f"{where}: runs-on must be a literal GitHub-hosted ubuntu label, got {runs_on!r}")
        t = job.get("timeout-minutes")
        if not (isinstance(t, int) and not isinstance(t, bool) and 1 <= t <= MAX_TIMEOUT):
            bad(f"{where}: timeout-minutes must be an integer in 1..{MAX_TIMEOUT}, got {t!r}")
        if job.get("continue-on-error") not in (None, False):
            bad(f"{where}: continue-on-error is not allowed")
        for forbidden in ("environment", "container", "services", "secrets", "uses"):
            if forbidden in job:
                bad(f"{where}: `{forbidden}` is not allowed")
        for i, step in enumerate(job.get("steps") or []):
            sw = f"{where} step {i + 1} ({step.get('name', step.get('uses', '?'))})"
            if "run" in step:
                run = str(step["run"])
                if "${{" in run:
                    bad(f"{sw}: `${{{{ }}}}` expression inside run: (pass it via env: instead)")
                if re.search(r"\bgit\s+(push|commit)\b", run):
                    bad(f"{sw}: git push/commit in a script")
            if "uses" in step:
                uses = str(step["uses"])
                m = re.fullmatch(r"(actions/[A-Za-z0-9_.-]+)@(\S+)", uses)
                if not m:
                    bad(f"{sw}: only first-party `actions/<name>@<ref>` actions are allowed, got {uses!r}")
                else:
                    ref = m.group(2)
                    if not (SHA_RE.match(ref) or (TAG_RE.match(ref) and not require_sha_pins)):
                        bad(f"{sw}: {uses!r} must be pinned to a "
                            f"{'40-hex commit SHA' if require_sha_pins else 'version tag or 40-hex commit SHA'}")
                    action = m.group(1)
                    with_ = step.get("with") or {}
                    if action == "actions/checkout" and with_.get("persist-credentials") is not False:
                        bad(f"{sw}: actions/checkout needs `persist-credentials: false`")
                    if action == "actions/upload-artifact":
                        r = with_.get("retention-days")
                        if not (isinstance(r, int) and 1 <= r <= MAX_RETENTION):
                            bad(f"{sw}: upload-artifact needs retention-days in 1..{MAX_RETENTION}, got {r!r}")

    forbidden = (r"\$\{\{[^}]*\bsecrets\b", r"GITHUB_TOKEN", r"\bgithub\.token\b", r"pull_request_target",
                 r"workflow_run", r"self-hosted")
    for pattern in forbidden:
        for line in text.splitlines():  # comments may discuss these words; only non-comment text counts
            if re.search(pattern, line.split("#", 1)[0]):
                bad(f"forbidden token /{pattern}/ on line: {line.strip()[:100]}")
                break
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--require-sha-pins", action="store_true", help="demand 40-hex SHA pins (use once the actions are pinned)")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    files = [Path(f) for f in args.files] or sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    if not files:
        print("ERROR: no workflow files found", file=sys.stderr)
        return 2
    problems: list[str] = []
    for f in files:
        problems += check_workflow(f.read_text(encoding="utf-8"), f.name, args.require_sha_pins)
    for p in problems:
        print(f" - {p}")
    print(f"{len(files)} workflow file(s) checked; {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
