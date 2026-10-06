#!/usr/bin/env python3
"""Regression suite: tools/build_ha_bundle.py and tools/validate_repo.py must keep every manifest `source` inside the repo.

Public-CI audit finding: the builder did `shutil.copy2(ROOT / source, OUT / source)` with no containment, so a pull request
changing deployment/ha-manifest.yaml could name `../x`, an absolute path, a symlink, `.git/config` or an untracked runner file
and have it copied into the uploaded bundle. Every case below must be REFUSED (UnsafePathError / non-zero exit), must leave
no bundle behind, and the one valid case must still build. Runs in throw-away git repositories; touches nothing else.

Symlink cases use real symlinks where the OS allows them (always on the Linux CI runner). Where it does not (Windows
without the symlink privilege) they fall back to a junction (directory) and to a git-index mode-120000 entry (file), and the
suite says so; on a POSIX host a failure to create a symlink is itself a failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import _safe_paths as sp  # noqa: E402
import build_ha_bundle as bhb  # noqa: E402
import validate_repo as vr  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


GOOD_MANIFEST = """\
schema_version: 2
release: "test"
home_assistant_packages:
  - source: home-assistant/packages/a.yaml
dashboard:
  source: home-assistant/dashboards/d.yaml
frontend_assets:
  - source: frontend/card/dist/card.js
firmware:
  source: firmware/fw.yaml
influxdb:
  - source: influxdb/tasks/t.flux
"""
GOOD_FILES = {
    "VERSION.yaml": "version: 1\n",
    "home-assistant/packages/a.yaml": "a: 1\n",
    "home-assistant/dashboards/d.yaml": "d: 1\n",
    "frontend/card/dist/card.js": "// card\n",
    "firmware/fw.yaml": "fw: 1\n",
    "influxdb/tasks/t.flux": "// flux\n",
}


class Repo:
    """A throw-away git repo (plus an `outside` sibling directory holding a secret the bundle must never contain)."""

    def __init__(self, manifest: str = GOOD_MANIFEST, files: dict[str, str] | None = None, track: bool = True):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "repo"
        self.outside = base / "outside"
        self.root.mkdir()
        self.outside.mkdir()
        (self.outside / "secret.yaml").write_text("TOP-SECRET-OUTSIDE\n", encoding="utf-8")
        (self.outside / "stolen.yaml").write_text("TOP-SECRET-OUTSIDE\n", encoding="utf-8")
        (self.outside / "secretdir").mkdir()
        (self.outside / "secretdir" / "a.yaml").write_text("TOP-SECRET-OUTSIDE\n", encoding="utf-8")
        git(self.root, "init", "-q")
        self.write("deployment/ha-manifest.yaml", manifest)
        for rel, text in (GOOD_FILES if files is None else files).items():
            self.write(rel, text)
        if track:
            self.track()

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def track(self) -> None:
        git(self.root, "add", "-A")

    def set_manifest(self, sources: list[str]) -> None:
        self.write("deployment/ha-manifest.yaml", "schema_version: 2\nrelease: t\nhome_assistant_packages:\n"
                   + "".join(f"  - source: {s}\n" for s in sources))

    def bundle(self) -> Path:
        return self.root / "dist" / "ecco-ha-bundle"

    def bundle_contains_secret(self) -> bool:
        b = self.bundle()
        return b.exists() and any("TOP-SECRET-OUTSIDE" in p.read_text(encoding="utf-8", errors="ignore")
                                  for p in b.rglob("*") if p.is_file())

    def close(self) -> None:
        self.tmp.cleanup()


def refused(repo: Repo, **kw) -> tuple[bool, str]:
    """(refused cleanly with UnsafePathError, no bundle and no secret left behind), message"""
    try:
        bhb.build(repo.root, **kw)
    except sp.UnsafePathError as exc:
        return (not repo.bundle().exists() and not repo.bundle_contains_secret()), str(exc)
    except Exception as exc:  # any other crash is also a failure of the contract
        return False, f"unexpected {type(exc).__name__}: {exc}"
    return False, "build succeeded"


def refusal_case(label: str, sources: list[str], setup=None, want: str | None = None, **kw) -> None:
    r = Repo(track=False)
    try:
        r.set_manifest(sources)
        if setup:
            setup(r)
        r.track()
        ok, msg = refused(r, **kw)
        check(f"REFUSED: {label}", ok and (want is None or want in msg), msg)
    finally:
        r.close()


# ---------------------------------------------------------------------------
print("[1] Valid manifest: every source (incl. frontend_assets) is bundled, review-only markers present")
# ---------------------------------------------------------------------------
r = Repo()
try:
    out = bhb.build(r.root)
    got = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    want = sorted([*GOOD_FILES, "ha-manifest.yaml", "README.md", "REVIEW-ONLY.txt"])
    check("bundle holds exactly the manifest sources + VERSION.yaml + ha-manifest.yaml + README + REVIEW-ONLY.txt", got == want, str(got))
    check("file contents are copied faithfully", all((out / k).read_text(encoding="utf-8") == v for k, v in GOOD_FILES.items()))
    check("REVIEW-ONLY marker and README say it is not a deployment artifact",
          "REVIEW ONLY" in (out / "REVIEW-ONLY.txt").read_text(encoding="utf-8") and "REVIEW ONLY" in (out / "README.md").read_text(encoding="utf-8"))
    out2 = bhb.build(r.root)
    check("a rebuild replaces the previous bundle", out2 == out and (out / "README.md").is_file())
finally:
    r.close()

# ---------------------------------------------------------------------------
print("[2] Path traversal and absolute paths")
# ---------------------------------------------------------------------------
refusal_case("'../outside/secret.yaml' (leading ..)", ["../outside/secret.yaml"])
refusal_case("'home-assistant/packages/../../../outside/secret.yaml' (embedded ..)", ["home-assistant/packages/../../../outside/secret.yaml"])
refusal_case("'home-assistant/packages/../packages/a.yaml' (.. even when it stays inside)", ["home-assistant/packages/../packages/a.yaml"])
refusal_case("'./home-assistant/packages/a.yaml' (. component)", ["./home-assistant/packages/a.yaml"])
refusal_case("POSIX absolute '/etc/passwd'", ["/etc/passwd"])
refusal_case("absolute path to a real file outside the repo", [], setup=lambda r: r.set_manifest([str(r.outside / "secret.yaml").replace("\\", "/")]))
refusal_case("Windows drive 'C:/Windows/win.ini'", ["C:/Windows/win.ini"])
refusal_case("backslash traversal 'home-assistant\\packages\\..\\..\\x.yaml'", ["home-assistant\\packages\\..\\..\\x.yaml"])
refusal_case("home dir '~/x.yaml'", ["~/x.yaml"])
refusal_case("8.3 short name tilde", ["home-assistant/PACKAG~1/a.yaml"])
refusal_case("trailing-dot component (Windows normalises it away)", ["home-assistant/packages./a.yaml"])
refusal_case("empty component '//'", ["home-assistant//packages/a.yaml"])
refusal_case("empty string source", [""])
refusal_case("non-string source (a list)", ["x"], setup=lambda r: r.write("deployment/ha-manifest.yaml",
             "home_assistant_packages:\n  - source: [home-assistant/packages/a.yaml]\n"))

# ---------------------------------------------------------------------------
print("[3] .git, workflows, secrets and files outside the approved directories")
# ---------------------------------------------------------------------------
refusal_case(".git/config", [".git/config"])
refusal_case("nested .git component", ["firmware/.git/config"])
refusal_case(".github/workflows/validate.yml", [".github/workflows/validate.yml"], setup=lambda r: r.write(".github/workflows/validate.yml", "x: 1\n"))
refusal_case("a tracked file outside the allow-list (tools/_safe_paths.py)", ["tools/_safe_paths.py"], setup=lambda r: r.write("tools/_safe_paths.py", "x=1\n"))
refusal_case("a tracked file at the repo root", ["README.md"], setup=lambda r: r.write("README.md", "hi\n"))
refusal_case("disallowed suffix (.sh) inside an allowed directory", ["firmware/run.sh"], setup=lambda r: r.write("firmware/run.sh", "echo\n"))
refusal_case("firmware/secrets.yaml", ["firmware/secrets.yaml"], setup=lambda r: r.write("firmware/secrets.yaml", "k: v\n"))
refusal_case("a *_private.yaml file", ["home-assistant/packages/x_private.yaml"], setup=lambda r: r.write("home-assistant/packages/x_private.yaml", "k: v\n"))
refusal_case("an .env file", ["firmware/.env.yaml"], setup=lambda r: r.write("firmware/.env.yaml", "k: v\n"))

# ---------------------------------------------------------------------------
print("[4] Symlinks (file, parent directory, junction) and the git-index symlink mode")
# ---------------------------------------------------------------------------
SYMLINKS_WORK = True
_probe = tempfile.TemporaryDirectory()
try:
    os.symlink(_probe.name, os.path.join(_probe.name, "probe"), target_is_directory=True)
except OSError:
    SYMLINKS_WORK = False
finally:
    _probe.cleanup()
if not SYMLINKS_WORK and os.name == "posix":
    check("this POSIX host can create symlinks (required for the real-symlink cases)", False)
print(f"        (real symlinks available: {SYMLINKS_WORK})")


def make_file_symlink(r: Repo) -> None:
    os.symlink(r.outside / "secret.yaml", r.root / "home-assistant" / "packages" / "link.yaml")


def make_dir_symlink(r: Repo) -> None:
    (r.root / "home-assistant" / "packages").rename(r.root / "home-assistant" / "packages_real")
    os.symlink(r.outside / "secretdir", r.root / "home-assistant" / "packages", target_is_directory=True)


def make_junction(r: Repo) -> None:
    (r.root / "home-assistant" / "packages").rename(r.root / "home-assistant" / "packages_real")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(r.root / "home-assistant" / "packages"), str(r.outside / "secretdir")],
                   check=True, capture_output=True)


def make_index_symlink(r: Repo) -> None:
    """A mode-120000 index entry whose working file is a plain file (exactly what core.symlinks=false checkouts look like)."""
    r.write("home-assistant/packages/link.yaml", str(r.outside / "secret.yaml"))
    blob = subprocess.run(["git", "-C", str(r.root), "hash-object", "-w", "home-assistant/packages/link.yaml"],
                          check=True, capture_output=True, text=True).stdout.strip()
    git(r.root, "add", "-A")
    git(r.root, "update-index", "--add", "--cacheinfo", f"120000,{blob},home-assistant/packages/link.yaml")


if SYMLINKS_WORK:
    refusal_case("symlinked FILE pointing outside the repo", ["home-assistant/packages/link.yaml"], setup=make_file_symlink, want="symlink")
    refusal_case("symlinked PARENT directory pointing outside the repo", ["home-assistant/packages/a.yaml"], setup=make_dir_symlink, want="symlink")
    refusal_case("symlinked file, with the git-tracked check disabled (containment alone must stop it)", ["home-assistant/packages/link.yaml"],
                 setup=make_file_symlink, want="symlink", require_tracked=False)
elif os.name == "nt":
    refusal_case("junctioned PARENT directory pointing outside the repo (Windows stand-in for a symlinked dir)", ["home-assistant/packages/a.yaml"],
                 setup=make_junction, want="symlink")
    print("  SKIP  real file symlinks need the Windows symlink privilege; the Linux CI runner exercises them. "
          "Stand-in below: git-index mode 120000.")
refusal_case("git-index symlink entry (mode 120000) for a file", ["home-assistant/packages/link.yaml"], setup=make_index_symlink,
             want="not a git-tracked regular file")
_t = tempfile.TemporaryDirectory()
try:
    tgt = Path(_t.name) / "t"
    tgt.mkdir()
    lnk = Path(_t.name) / "l"
    made = False
    try:
        os.symlink(tgt, lnk, target_is_directory=True)
        made = True
    except OSError:
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(lnk), str(tgt)], capture_output=True).returncode == 0
    if made:
        check("is_link_like(): link/junction -> True, ordinary directory -> False", sp.is_link_like(lnk) and not sp.is_link_like(tgt))
finally:
    _t.cleanup()

# ---------------------------------------------------------------------------
print("[5] Untracked files, duplicate destinations, directories, missing files")
# ---------------------------------------------------------------------------
r = Repo(track=False)
try:
    r.track()
    r.write("home-assistant/packages/untracked.yaml", "u: 1\n")  # written AFTER tracking => untracked
    r.set_manifest(["home-assistant/packages/untracked.yaml"])
    git(r.root, "add", "deployment/ha-manifest.yaml")
    ok, msg = refused(r)
    check("REFUSED: untracked file in an allowed directory", ok and "git-tracked" in msg, msg)
    try:
        bhb.build(r.root, require_tracked=False)
        check("--allow-untracked (require_tracked=False) lets the same file through (containment still applies)", True)
    except sp.UnsafePathError as exc:
        check("--allow-untracked (require_tracked=False) lets the same file through (containment still applies)", False, str(exc))
finally:
    r.close()
refusal_case("duplicate destination", ["home-assistant/packages/a.yaml", "home-assistant/packages/a.yaml"], want="duplicate")
refusal_case("a directory named as a source", ["home-assistant/packages"])
refusal_case("a source that does not exist", ["home-assistant/packages/missing.yaml"], want="does not exist")
refusal_case("a manifest with no sources", [], setup=lambda r: r.write("deployment/ha-manifest.yaml", "schema_version: 2\n"), want="no sources")
refusal_case("valid sources followed by one bad source: nothing is half-built", ["home-assistant/packages/a.yaml", "../outside/secret.yaml"])
r = Repo()
try:
    bhb.build(r.root)
    r.set_manifest(["../outside/secret.yaml"])
    ok, msg = refused(r)
    check("a refused build also removes the bundle left by an earlier successful build (no stale artifact)", ok, msg)
finally:
    r.close()

# ---------------------------------------------------------------------------
print("[6] The CLI exits non-zero (2) and prints REFUSED; the real manifest is clean")
# ---------------------------------------------------------------------------
r = Repo(track=False)
try:
    r.set_manifest(["../outside/secret.yaml"])
    r.track()
    for rel in ("tools/build_ha_bundle.py", "tools/_safe_paths.py"):
        (r.root / "tools").mkdir(exist_ok=True)
        (r.root / rel).write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    p = subprocess.run([sys.executable, str(r.root / "tools" / "build_ha_bundle.py")], capture_output=True, text=True, cwd=r.root)
    check("build_ha_bundle.py on a malicious manifest: exit 2, 'REFUSED' on stderr, no bundle", p.returncode == 2 and "REFUSED" in p.stderr
          and not r.bundle().exists(), f"rc={p.returncode} {p.stderr!r}")
finally:
    r.close()

real_manifest = ROOT / "deployment" / "ha-manifest.yaml"
import yaml  # noqa: E402

real_sources = bhb.collect_sources(yaml.safe_load(real_manifest.read_text(encoding="utf-8")))
check("the real manifest names sources (and frontend_assets are among them)",
      len(real_sources) > 10 and any(s.startswith("frontend/") for s in real_sources), str(len(real_sources)))
bad_real = []
for s in [*real_sources, "VERSION.yaml"]:
    try:
        sp.resolve_source(ROOT, s, require_tracked=(ROOT / ".git").exists())
    except sp.UnsafePathError as exc:
        bad_real.append(str(exc))
check("every real manifest source passes containment (tracked, regular, inside the repo)", not bad_real, str(bad_real))

# ---------------------------------------------------------------------------
print("[7] tools/validate_repo.py applies the same containment to the manifest")
# ---------------------------------------------------------------------------


def validator_errors(sources: list[str], setup=None) -> list[str]:
    r = Repo(track=False)
    saved = (vr.ROOT, list(vr.ERRORS))
    try:
        r.set_manifest(sources)
        if setup:
            setup(r)
        vr.ROOT = r.root
        vr.ERRORS.clear()
        vr.validate_deployment_sources()
        return list(vr.ERRORS)
    finally:
        vr.ROOT = saved[0]
        vr.ERRORS[:] = saved[1]
        r.close()


check("validate_repo accepts a clean manifest", validator_errors(["home-assistant/packages/a.yaml"]) == [])
check("validate_repo rejects '../outside/secret.yaml'", any("outside" in e or ".." in e for e in validator_errors(["../outside/secret.yaml"])))
check("validate_repo rejects an absolute source", bool(validator_errors(["/etc/passwd"])))
check("validate_repo rejects a missing source", any("does not exist" in e for e in validator_errors(["home-assistant/packages/nope.yaml"])))
check("validate_repo rejects '.git/config'", bool(validator_errors([".git/config"])))
if SYMLINKS_WORK:
    check("validate_repo rejects a symlinked source", bool(validator_errors(["home-assistant/packages/link.yaml"], setup=make_file_symlink)))

# ---------------------------------------------------------------------------
print("[8] Lexical rules table")
# ---------------------------------------------------------------------------
LEX_OK = ["home-assistant/packages/ecco_pro.yaml", "frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js",
          "influxdb/tasks/ecco_battery_outlook_5m.flux", "VERSION.yaml", "deployment/ha-manifest.yaml"]
LEX_BAD = ["", "firmware/x" + chr(0) + ".yaml", "/abs.yaml", "a/../b.yaml", "..", "../x.yaml", "firmware/./x.yaml", "firmware\\x.yaml", "C:/x.yaml", "firmware/x.yaml ", "firmware/.git/x.yaml",
           ".github/workflows/x.yml", "firmware/secrets.yaml", "docs/readme.md", "firmware/x.exe", "firmware/x.yaml\n", None, 5, ["firmware/x.yaml"]]
check("lexical accept list", all(_ok for _ok in (sp.check_relative_source(s) for s in LEX_OK)))
bad_accepted = []
for s in LEX_BAD:
    try:
        sp.check_relative_source(s)
        bad_accepted.append(s)
    except sp.UnsafePathError:
        pass
check("lexical reject list: every malformed / out-of-policy source is refused", not bad_accepted, str(bad_accepted))

if FAILURES:
    print(f"\n{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print(f" - {f}")
    sys.exit(1)
print("\nAll build_ha_bundle containment checks passed")
