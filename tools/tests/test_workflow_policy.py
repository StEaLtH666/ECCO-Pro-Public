#!/usr/bin/env python3
"""Regression suite: the workflows under .github/workflows keep the public-fork-safe security shape.

Runs tools/check_workflows.py over the real workflow files (must be clean), then over deliberately unsafe variants of a
known-good workflow (each mutation must be reported), so the checker itself cannot silently go blind. Also pins the
properties this baseline promises: no historical generator workflows, no write permission, no pull_request_target /
workflow_run / self-hosted, every job has a timeout, checkout never persists credentials, the test job reads its roots
from tools/offline_test_roots.txt through the runner (no copy of the list in the workflow), and no secret is referenced.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import check_workflows as cw  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


WF_DIR = ROOT / ".github" / "workflows"
FILES = sorted(WF_DIR.glob("*.y*ml"))

# ---------------------------------------------------------------------------
print("[1] The real workflows")
# ---------------------------------------------------------------------------
check("workflow files exist", bool(FILES), str(FILES))
check("the public baseline ships validation/build-review workflows only: exactly validate.yml",
      [f.name for f in FILES] == ["validate.yml"], str([f.name for f in FILES]))
check("no historical generator workflow is present (generate-*.yml)", not [f for f in FILES if f.name.startswith("generate-")])
real_problems = [p for f in FILES for p in cw.check_workflow(f.read_text(encoding="utf-8"), f.name, require_sha_pins=True)]
check("every real workflow satisfies the security policy INCLUDING --require-sha-pins (every action at a 40-hex commit SHA)",
      not real_problems, "; ".join(real_problems))

VALIDATE = (WF_DIR / "validate.yml").read_text(encoding="utf-8")
DOC = yaml.safe_load(VALIDATE)
JOBS = DOC["jobs"]
EVENTS = DOC.get("on", DOC.get(True))
check("events are exactly pull_request, push and workflow_dispatch", set(EVENTS) == {"pull_request", "push", "workflow_dispatch"}, str(set(EVENTS)))
check("push is limited to main", EVENTS["push"] == {"branches": ["main"]}, str(EVENTS["push"]))
check("top-level permissions are exactly contents: read", DOC["permissions"] == {"contents": "read"})
check("no job overrides permissions", not any("permissions" in j for j in JOBS.values()))
check("every job has an explicit timeout-minutes <= 240", all(isinstance(j.get("timeout-minutes"), int) and j["timeout-minutes"] <= 240 for j in JOBS.values()),
      str({k: j.get("timeout-minutes") for k, j in JOBS.items()}))
check("every job runs on a pinned GitHub-hosted ubuntu label", all(re.fullmatch(r"ubuntu-\d+\.\d+", j["runs-on"]) for j in JOBS.values()))
checkouts = [s for j in JOBS.values() for s in j["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
check("every checkout step sets persist-credentials: false", checkouts and all(s.get("with", {}).get("persist-credentials") is False for s in checkouts), str(len(checkouts)))
check("only first-party actions/* are used", all(re.match(r"actions/", s["uses"]) for j in JOBS.values() for s in j["steps"] if "uses" in s))
USES = re.findall(r"(?m)^\s*(?:- )?uses: (actions/[a-z-]+)@(\S+)(?: # (\S+))?$", VALIDATE)
check("every action ref is a 40-hex commit SHA with its upstream release tag as the trailing comment (no tag, no branch ref)",
      bool(USES) and all(re.fullmatch(r"[0-9a-f]{40}", ref) and re.fullmatch(r"v\d+\.\d+\.\d+", tag) for _a, ref, tag in USES), str(USES))
check("each action is pinned to ONE commit everywhere it is used (no drift between jobs)",
      all(len({(ref, tag) for a2, ref, tag in USES if a2 == a}) == 1 for a, _r, _t in USES))
check("the policy step enforces the SHA pins in CI",
      "tools/check_workflows.py --require-sha-pins" in "\n".join(s.get("run", "") for s in JOBS["repo-checks"]["steps"]))
check("no secrets / tokens / environments are referenced", not re.search(r"\$\{\{[^}]*secrets|GITHUB_TOKEN|github\.token|environment:", "\n".join(l.split("#", 1)[0] for l in VALIDATE.splitlines())))
check("the only artifact is the review-only HA bundle with short retention",
      [(s["with"]["name"], s["with"]["retention-days"]) for j in JOBS.values() for s in j["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
      == [("ecco-ha-bundle-REVIEW-ONLY-not-for-deployment", 7)])
check("ci-ok aggregates every other job and runs even when they fail",
      JOBS["ci-ok"]["if"] == "always()" and set(JOBS["ci-ok"]["needs"]) == set(JOBS) - {"ci-ok"})
check("no path filtering and no dedupe/skip logic (events carry no paths:, no job-level if except ci-ok)",
      not any("paths" in (v or {}) for v in EVENTS.values() if isinstance(v, dict)) and [k for k, j in JOBS.items() if "if" in j] == ["ci-ok"])

tests_job = JOBS["offline-tests"]
runs = "\n".join(s.get("run", "") for s in tests_job["steps"])
check("the tests job reads roots via tools/run_offline_tests.py (--root from the matrix), never a copy of the list",
      "tools/run_offline_tests.py --root" in runs and "$TEST_ROOT" in runs and "tools/offline_test_roots.txt" not in VALIDATE.split("jobs:", 1)[1].replace("# tools/offline_test_roots.txt", ""),
      runs)
check("the matrix comes from the plan job's validated output", tests_job["strategy"]["matrix"]["root"] == "${{ fromJSON(needs.plan-tests.outputs.roots) }}"
      and tests_job["needs"] == "plan-tests")
check("the plan job calls --list-roots-json", "--list-roots-json" in "\n".join(s.get("run", "") for s in JOBS["plan-tests"]["steps"]))
fw = JOBS["firmware-compile"]
check("firmware: classic and ESP32-S3 variants both configured and compiled",
      {m["config"] for m in fw["strategy"]["matrix"]["include"]} == {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                                                                    "firmware/ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml"}
      and any("esphome config" in s.get("run", "") for s in fw["steps"]) and any("esphome compile" in s.get("run", "") for s in fw["steps"]))
check("firmware: ESPHome is pinned inside [2026.8.2, 2026.9.0)", re.findall(r"esphome==([\d.]+)", VALIDATE) == ["2026.8.2"])
check("firmware: placeholder secrets are removed again even on failure", any(s.get("if") == "always()" and "rm -f firmware/secrets.yaml" in s.get("run", "") for s in fw["steps"]))
repo_runs = "\n".join(s.get("run", "") for s in JOBS["repo-checks"]["steps"])
check("repo-checks keep validate_repo, the write-surface analysis, the workflow policy and the PowerShell parse",
      all(x in repo_runs for x in ("tools/validate_repo.py", "tools/analyze_write_surface.py", "tools/check_workflows.py", "ParseFile")))
check("the bundle job builds with the hardened builder and uploads from dist/ecco-ha-bundle",
      any("tools/build_ha_bundle.py" in s.get("run", "") for s in JOBS["ha-bundle"]["steps"]))

# ---------------------------------------------------------------------------
print("[2] Mutation: every unsafe change to a good workflow is reported")
# ---------------------------------------------------------------------------


def mutated(old: str, new: str, count: int = 1) -> str:
    assert old in VALIDATE, f"mutation anchor missing: {old!r}"
    return VALIDATE.replace(old, new, count)


def flagged(label: str, text: str, want: str) -> None:
    probs = cw.check_workflow(text, "mutant")
    check(f"policy flags: {label}", any(want in p for p in probs), "; ".join(probs) or "no problems reported")


CHECKOUT = re.search(r"      - uses: actions/checkout@[0-9a-f]{40} # v[\d.]+\n", VALIDATE).group(0)
SETUP_PY = re.search(r"      - uses: actions/setup-python@[0-9a-f]{40} # v[\d.]+\n", VALIDATE).group(0)
SETUP_REF = SETUP_PY.split("uses: ", 1)[1].split(" #", 1)[0]          # actions/setup-python@<sha>
check("the unmutated workflow is clean (control), also under --require-sha-pins",
      cw.check_workflow(VALIDATE, "ok") == [] and cw.check_workflow(VALIDATE, "ok", require_sha_pins=True) == [])
flagged("pull_request_target event", mutated("on:\n  pull_request:\n", "on:\n  pull_request_target:\n"), "pull_request_target")
flagged("workflow_run event", mutated("  workflow_dispatch:\n\nconcurrency", "  workflow_dispatch:\n  workflow_run:\n    workflows: [x]\n\nconcurrency"), "workflow_run")
flagged("schedule event", mutated("  workflow_dispatch:\n\nconcurrency", "  workflow_dispatch:\n  schedule:\n    - cron: '0 0 * * *'\n\nconcurrency"), "schedule")
flagged("push to every branch", mutated("  push:\n    branches:\n      - main\n", "  push:\n"), "push must be limited")
flagged("workflow_dispatch inputs", mutated("  workflow_dispatch:\n\nconcurrency", "  workflow_dispatch:\n    inputs:\n      x:\n        type: string\n\nconcurrency"), "inputs")
flagged("contents: write at top level", mutated("permissions:\n  contents: read\n\njobs:", "permissions:\n  contents: write\n\njobs:"), "top-level permissions")
flagged("write permission on one job", mutated("    name: Repository checks\n", "    name: Repository checks\n    permissions:\n      contents: write\n"), "job-level permissions")
flagged("id-token / pull-requests permission on a job", mutated("    name: Repository checks\n", "    name: Repository checks\n    permissions:\n      id-token: write\n"), "job-level permissions")
flagged("missing top-level permissions", mutated("permissions:\n  contents: read\n\njobs:", "jobs:"), "top-level permissions")
flagged("self-hosted runner", mutated("    name: Repository checks\n    runs-on: ubuntu-24.04", "    name: Repository checks\n    runs-on: self-hosted"), "runs-on")
flagged("runner chosen by expression", mutated("    name: Repository checks\n    runs-on: ubuntu-24.04", "    name: Repository checks\n    runs-on: ${{ github.event.inputs.r }}"), "runs-on")
flagged("job without timeout", mutated("    timeout-minutes: 20\n", "", 1), "timeout-minutes")
flagged("six-hour timeout", mutated("    timeout-minutes: 20\n", "    timeout-minutes: 360\n"), "timeout-minutes")
flagged("checkout persisting credentials", mutated(CHECKOUT + "        with:\n          persist-credentials: false\n", CHECKOUT, 1),
        "persist-credentials")
flagged("checkout with persist-credentials: true", mutated("          persist-credentials: false\n", "          persist-credentials: true\n", 1), "persist-credentials")
flagged("third-party action", mutated(SETUP_PY, "      - uses: someone/cache-thing@v1\n", 1), "first-party")
flagged("action pinned to a moving branch", mutated(SETUP_REF, "actions/setup-python@main", 1), "pinned")
flagged("docker:// action", mutated(SETUP_PY, "      - uses: docker://alpine:3\n", 1), "first-party")
flagged("local action", mutated(SETUP_PY, "      - uses: ./.github/actions/x\n", 1), "first-party")
flagged("event data inside a run script (script injection)", mutated("run: python tools/validate_repo.py", "run: echo ${{ github.event.pull_request.title }}"), "expression inside run")
flagged("matrix value inside a run script", mutated('run: esphome config "$FIRMWARE_CONFIG"', 'run: esphome config ${{ matrix.config }}'), "expression inside run")
flagged("secret reference", mutated("      - name: Workflow security policy\n", "      - name: x\n        env:\n          K: ${{ secrets.DEPLOY_KEY }}\n        run: true\n      - name: Workflow security policy\n"), "secrets")
flagged("GITHUB_TOKEN use", mutated("      - name: Workflow security policy\n", "      - name: x\n        env:\n          K: ${{ github.token }}\n        run: true\n      - name: Workflow security policy\n"), "github")
flagged("git push in a script", mutated("run: python tools/validate_repo.py", "run: git push origin HEAD"), "git push")
flagged("artifact with default 90-day retention", mutated("          retention-days: 7\n", ""), "retention-days")
flagged("artifact kept 90 days", mutated("retention-days: 7", "retention-days: 90"), "retention-days")
flagged("continue-on-error", mutated("    name: Repository checks\n", "    name: Repository checks\n    continue-on-error: true\n"), "continue-on-error")
flagged("a deployment environment", mutated("    name: Repository checks\n", "    name: Repository checks\n    environment: production\n"), "environment")
flagged("a reusable workflow call (job-level uses)", mutated("    name: Repository checks\n", "    name: Repository checks\n    uses: org/repo/.github/workflows/x.yml@main\n"), "uses")
flagged("broken YAML", "on: [push\njobs: {", "parse")

# ---------------------------------------------------------------------------
print("[3] SHA pins")
# ---------------------------------------------------------------------------
tagged = VALIDATE.replace(SETUP_REF, "actions/setup-python@v5", 1)
check("a version-tag ref passes the default policy but is reported under --require-sha-pins (the CI setting)",
      cw.check_workflow(tagged, "x") == [] and any("40-hex commit SHA" in p for p in cw.check_workflow(tagged, "x", require_sha_pins=True)))
check("a short or upper-case SHA is not a pin",
      all(cw.check_workflow(VALIDATE.replace(SETUP_REF, r, 1), "x", require_sha_pins=True) != []
          for r in (SETUP_REF[:-1], "actions/setup-python@" + SETUP_REF.split("@", 1)[1].upper())))

if FAILURES:
    print(f"\n{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f" - {f}")
    sys.exit(1)
print("\nAll workflow policy checks passed")
