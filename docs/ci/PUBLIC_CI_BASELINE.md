# Public CI baseline

One workflow, `.github/workflows/validate.yml`. Validation and build-review only. Simple on purpose: every event runs every
check (no path filtering, no caching of results, no "skip if already green"). Public GitHub-hosted minutes are free, so this
optimises for security, simplicity, correctness and debuggability, not for saving minutes.

## Jobs

| Job | What it does | Timeout |
|---|---|---|
| `repo-checks` | PowerShell parse of `tools/*.ps1`, `tools/validate_repo.py`, `tools/check_workflows.py` (workflow security policy), `tools/analyze_write_surface.py` (fails closed on unknown register extent / unclassified bus access) | 20 min |
| `plan-tests` | `tools/run_offline_tests.py --list-roots-json`: reads `tools/offline_test_roots.txt`, fails closed, emits the matrix | 5 min |
| `offline-tests` (matrix, one leg per root) | `tools/run_offline_tests.py --root <root>`: every `test_*.py` under that root, all run to completion, exit 1 if any failed or timed out | 240 min |
| `firmware-compile` (matrix: classic ESP32, ESP32-S3) | `esphome config` + `esphome compile` with `esphome==2026.8.2` and fake placeholder secrets | 60 min |
| `ha-bundle` | `tools/build_ha_bundle.py` (hardened) and a **review-only** artifact, 7-day retention | 10 min |
| `ci-ok` | Fails unless every other job succeeded. The one required status check | 5 min |

## Fork / pull-request threat model

A fork PR is arbitrary code. It can change firmware, tests, Python tools, Home Assistant YAML and the manifest, and all of it
runs on an ephemeral GitHub-hosted runner. Safety comes from there being nothing to steal or abuse:

* no secrets are referenced; the firmware job writes obviously fake `ci-test` credentials and deletes them again;
* token is `contents: read` only, checkout uses `persist-credentials: false`, no job overrides permissions;
* no `pull_request_target`, `workflow_run`, schedule, self-hosted runner, environment, deploy or `git push`;
* no `${{ }}` expression inside any `run:` script (matrix and event values go through `env:`), so event data cannot become
  shell code; the matrix is built from `tools/offline_test_roots.txt` by a tool that only emits `[A-Za-z0-9_./-]` strings;
* first-party `actions/*` only; nothing produced by a job is consumed by a later privileged step;
* the runner has ordinary internet egress (pip, PlatformIO) but no route to any production system.

`tools/check_workflows.py` enforces this shape on every run and `tools/tests/test_workflow_policy.py` proves, with unsafe
mutations of the real workflow, that the checker cannot go blind. Note the policy checker lives in the tree under test: a PR
can weaken it, so a reviewer must read any PR that touches `.github/` or `tools/check_workflows.py`. Branch protection (required
review for `.github/**` via CODEOWNERS) is the control that closes that gap; it is a repository setting, not a file in this change.

## HA bundle

`tools/build_ha_bundle.py` and `tools/validate_repo.py` share `tools/_safe_paths.py`. A manifest `source` is refused (exit 2,
no bundle left behind) unless it is a clean repo-relative path (no `..`, `.`, absolute, backslash, drive, `~`, NUL, control
character, trailing dot/space, `.git*` component), under `home-assistant/packages|dashboards`, `influxdb`, `frontend` or
`firmware` with a `.yaml/.yml/.flux/.js/.json/.md` suffix (plus `VERSION.yaml` and the manifest), not credential-shaped
(`secrets*`, `.env*`, `*_private.yaml`, `*.pem`, `*.key`), no component a symlink or junction, a regular file, resolving
inside the repo root, and git-tracked as mode 100644/100755 (`--allow-untracked` relaxes only the tracked check, for a source
archive). Every `source` anywhere in the manifest is bundled, which also fixes `frontend_assets` being listed but never copied.

The bundle is **review only**. On a PR it is built from unreviewed code; it contains `REVIEW-ONLY.txt`, the artifact is named
`ecco-ha-bundle-REVIEW-ONLY-not-for-deployment`, and no workflow consumes it. Deploy only from a reviewed, merged commit.
Regression suite: `tools/tests/test_build_ha_bundle_containment.py`.

## Action pins

Every `uses:` is pinned to the full 40-hex commit SHA of an official `actions/*` release, with the release tag as a trailing
comment, and the `repo-checks` job runs `python tools/check_workflows.py --require-sha-pins`, so a tag or branch ref fails CI.

| Action | Release | Commit SHA |
|---|---|---|
| `actions/checkout` | v4.4.0 | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/setup-python` | v5.6.0 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/upload-artifact` | v4.6.2 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |

Resolved on 2026-10-06 from the official repositories (each tag is a published, non-draft release). To update a pin, resolve
the new release tag to its commit on the official repository, change the SHA and the comment together, and keep the table above
in step. Automated pin updates (Dependabot for `github-actions`) are a planned post-0.9.0 improvement.

## Not in this baseline

The experimental optimised/dedupe selector design (`docs/ci/proposed/` on the CI-cost branch) and all historical
`contents: write` generator workflows (`generate-dashboard-*`, `generate-stage33-six-slot`) are deliberately absent.
