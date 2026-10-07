#!/usr/bin/env python3
"""Regression suite: tools/build_ha_bundle.py and tools/validate_repo.py must keep every manifest `source` inside the repo.

Public-CI audit finding: the builder did `shutil.copy2(ROOT / source, OUT / source)` with no containment, so a pull request
changing deployment/ha-manifest.yaml could name `../x`, an absolute path, a symlink, `.git/config` or an untracked runner file
and have it copied into the uploaded bundle. Every case below must be REFUSED (UnsafePathError / non-zero exit), must leave
no bundle behind, and the one valid case must still build. Runs in throw-away git repositories; touches nothing else.

Symlink cases use real symlinks where the OS allows them (always on the Linux CI runner). Where it does not (Windows
without the symlink privilege) they fall back to a junction (directory), and the suite says so; on a POSIX host a failure to
create a symlink is itself a failure. The git-index mode-120000 cases run on every host under both core.symlinks settings,
and each first asserts (FIXTURE) that git really records the state it names at build time: a later `git add` can rewrite it.
"""

from __future__ import annotations

import errno
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


def index_modes(r: Repo, rel: str) -> list[str]:
    """Modes of git's index records for exactly `rel` (literal pathspec, exact path); [] when git records nothing."""
    out = subprocess.run(["git", "--literal-pathspecs", "-C", str(r.root), "ls-files", "--stage", "-z", "--", rel],
                         check=True, capture_output=True).stdout
    return [meta.split(b" ")[0].decode() for meta, _, path in (rec.partition(b"\t") for rec in out.split(b"\0") if rec)
            if path == rel.encode("utf-8")]


def index_is(expected: dict[str, list[str]]):
    """precondition: at build time git's index holds exactly these record modes for these paths."""
    def holds(r: Repo) -> tuple[bool, str]:
        got = {rel: index_modes(r, rel) for rel in expected}
        return got == expected, f"git index at build time: {got}"
    return holds


def prepared(label: str, sources: list[str], setup, after_track, precondition) -> Repo:
    """setup -> `git add -A` -> after_track (state the final add must not rewrite) -> FIXTURE check of the precondition."""
    r = Repo(track=False)
    try:
        r.set_manifest(sources)
        if setup:
            setup(r)
        r.track()
        if after_track:
            after_track(r)
        if precondition:
            held, detail = precondition(r)
            check(f"FIXTURE: {label}", held, detail)
    except BaseException:
        r.close()
        raise
    return r


def refusal_case(label: str, sources: list[str], setup=None, want: str | None = None, *, after_track=None,
                 precondition=None, **kw) -> None:
    r = prepared(label, sources, setup, after_track, precondition)
    try:
        ok, msg = refused(r, **kw)
        check(f"REFUSED: {label}", ok and (want is None or want in msg), msg)
    finally:
        r.close()


def accepted_case(label: str, sources: list[str], setup=None, *, after_track=None, precondition=None) -> None:
    r = prepared(label, sources, setup, after_track, precondition)
    try:
        try:
            out = bhb.build(r.root)
            ok = all((out / s).read_bytes() == (r.root / s).read_bytes() for s in sources)
            msg = "bundled byte-identical" if ok else "bundle content differs"
        except Exception as exc:  # noqa: BLE001 - any refusal or crash fails this case
            ok, msg = False, f"{type(exc).__name__}: {exc}"
        check(f"ACCEPTED: {label}", ok, msg)
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


LINK = "home-assistant/packages/link.yaml"


def make_index_symlink(r: Repo) -> None:
    """A mode-120000 index entry whose working file is a plain file holding the link text: exactly what a checkout with
    core.symlinks=false (the Git for Windows default) writes for a committed symlink. The repo is configured that way
    explicitly: under core.symlinks=true (the Linux default) the `git add -A` that refusal_case() runs after setup sees a
    type change and re-stages the plain file as a REGULAR file (100644), so on the hosted Linux runner this case silently
    built an ordinary tracked file (2026-10-06). Its FIXTURE precondition now pins the index state at build time."""
    git(r.root, "config", "core.symlinks", "false")
    r.write(LINK, str(r.outside / "secret.yaml"))
    blob = subprocess.run(["git", "-C", str(r.root), "hash-object", "-w", LINK],
                          check=True, capture_output=True, text=True).stdout.strip()
    git(r.root, "add", "-A")
    git(r.root, "update-index", "--add", "--cacheinfo", f"120000,{blob},{LINK}")


def link_text_file(r: Repo) -> None:
    """A symlink-capable git (core.symlinks=true, the Linux default) and a plain working file holding a link text."""
    git(r.root, "config", "core.symlinks", "true")
    r.write(LINK, str(r.outside / "secret.yaml"))


def index_records_link(rel: str, target: str):
    """after_track: git records `rel` as a symlink to outside/`target` (mode 120000) while the working tree keeps what is
    there - a type change for a plain file; for a real directory --replace drops the entries below it (one path, one entry)."""
    def record(r: Repo) -> None:
        blob = subprocess.run(["git", "-C", str(r.root), "hash-object", "-w", "--stdin"], input=str(r.outside / target).encode("utf-8"),
                              check=True, capture_output=True).stdout.decode().strip()
        git(r.root, "update-index", "--add", "--replace", "--cacheinfo", f"120000,{blob},{rel}")
    return record


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
refusal_case("git-index symlink entry (mode 120000) for a file", [LINK], setup=make_index_symlink,
             want="not a git-tracked regular file", precondition=index_is({LINK: ["120000"]}))
refusal_case("git-index symlink entry (mode 120000) over a plain working file on a symlink-capable git (core.symlinks=true: a type change)",
             [LINK], setup=link_text_file, after_track=index_records_link(LINK, "secret.yaml"),
             want="not a git-tracked regular file", precondition=index_is({LINK: ["120000"]}))
refusal_case("git-index symlink entry (mode 120000) for the PARENT directory (the working tree keeps a real directory)",
             ["home-assistant/packages/a.yaml"], after_track=index_records_link("home-assistant/packages", "secretdir"),
             want="not a git-tracked regular file",
             precondition=index_is({"home-assistant/packages": ["120000"], "home-assistant/packages/a.yaml": []}))
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
print("[4b] The git-index check is exact (no pathspec globbing, one merged entry); a path-walk error is a refusal, not a crash")
# ---------------------------------------------------------------------------
GLOB = "home-assistant/packages/x[1].yaml"


def glob_hazard(r: Repo) -> tuple[bool, str]:
    """precondition: x[1].yaml is untracked, yet git's DEFAULT (glob) pathspec for it matches the tracked x1.yaml."""
    held, detail = index_is({GLOB: [], "home-assistant/packages/x1.yaml": ["100644"]})(r)
    globbed = subprocess.run(["git", "-C", str(r.root), "ls-files", "--", GLOB], check=True, capture_output=True, text=True).stdout.split()
    return (held and (r.root / GLOB).is_file() and globbed == ["home-assistant/packages/x1.yaml"],
            f"{detail}; default pathspec {GLOB!r} matched {globbed}")


def make_unmerged(rel: str):
    """after_track: replace rel's merged entry by conflict stages 1-3 (what an unresolved merge leaves in the index)."""
    def unmerge(r: Repo) -> None:
        blob = subprocess.run(["git", "-C", str(r.root), "hash-object", "-w", rel], check=True, capture_output=True,
                              text=True).stdout.strip()
        info = f"0 {'0' * len(blob)}\t{rel}\n" + "".join(f"100644 {blob} {stage}\t{rel}\n" for stage in (1, 2, 3))
        subprocess.run(["git", "-C", str(r.root), "update-index", "--index-info"], input=info.encode("utf-8"), check=True,
                       capture_output=True)
    return unmerge


refusal_case("an UNTRACKED file whose name, read as a git glob, matches a tracked file ('x[1].yaml' vs 'x1.yaml')", [GLOB],
             setup=lambda r: r.write("home-assistant/packages/x1.yaml", "x1: 1\n"), after_track=lambda r: r.write(GLOB, "UNTRACKED\n"),
             want="not a git-tracked regular file", precondition=glob_hazard)
refusal_case("an unmerged (conflicted) index entry: stages 1-3, no merged stage 0", ["home-assistant/packages/a.yaml"],
             after_track=make_unmerged("home-assistant/packages/a.yaml"), want="not a git-tracked regular file",
             precondition=index_is({"home-assistant/packages/a.yaml": ["100644", "100644", "100644"]}))
refusal_case("a parent component that is a regular FILE ('a.yaml/x.yaml': ENOTDIR on POSIX)", ["home-assistant/packages/a.yaml/x.yaml"],
             want="does not exist")


def walk_error_refused(err: int) -> tuple[bool, str]:
    """resolve_source() while every lstat() of the 'packages' component fails with `err` (deterministic on any host)."""
    r = Repo()
    target = os.path.normcase(str(r.root / "home-assistant" / "packages"))
    real_lstat = os.lstat

    def failing_lstat(path, *args, **kwargs):
        if os.path.normcase(os.fspath(path)) == target:
            raise OSError(err, os.strerror(err), os.fspath(path))
        return real_lstat(path, *args, **kwargs)

    os.lstat = failing_lstat
    try:
        sp.resolve_source(r.root, "home-assistant/packages/a.yaml")
        return False, "accepted"
    except sp.UnsafePathError as exc:
        return True, str(exc)
    except Exception as exc:  # noqa: BLE001 - a crash is exactly what this case guards against
        return False, f"unexpected {type(exc).__name__}: {exc}"
    finally:
        os.lstat = real_lstat
        r.close()


for _name in ("ENOTDIR", "EACCES", "ELOOP"):
    _ok, _msg = walk_error_refused(getattr(errno, _name))
    check(f"an {_name} while inspecting a path component is a refusal (UnsafePathError), not a crash", _ok, _msg)

accepted_case("a TRACKED source whose name holds git glob characters ('x[1].yaml' is matched literally)", [GLOB],
              setup=lambda r: r.write(GLOB, "x: 1\n"), precondition=index_is({GLOB: ["100644"]}))
accepted_case("a tracked executable source (mode 100755)", ["home-assistant/packages/a.yaml"],
              after_track=lambda r: git(r.root, "update-index", "--chmod=+x", "home-assistant/packages/a.yaml"),
              precondition=index_is({"home-assistant/packages/a.yaml": ["100755"]}))
NON_ASCII = "home-assistant/packages/caf" + chr(0xE9) + ".yaml"
accepted_case("a tracked source with a non-ASCII name (exact UTF-8 match)", [NON_ASCII],
              setup=lambda r: r.write(NON_ASCII, "c: 1\n"), precondition=index_is({NON_ASCII: ["100644"]}))

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
check("validate_repo reports (never crashes on) a source whose parent component is a file",
      any("does not exist" in e for e in validator_errors(["home-assistant/packages/a.yaml/x.yaml"])))

# ---------------------------------------------------------------------------
print("[8] Lexical rules table")
# ---------------------------------------------------------------------------
LEX_OK = ["home-assistant/packages/ecco_pro.yaml", "frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js",
          "influxdb/tasks/ecco_battery_outlook_5m.flux", "VERSION.yaml", "deployment/ha-manifest.yaml"]
LEX_BAD = ["", "firmware/x" + chr(0) + ".yaml", "firmware/x" + chr(0xD800) + ".yaml", "/abs.yaml", "a/../b.yaml", "..", "../x.yaml", "firmware/./x.yaml", "firmware\\x.yaml", "C:/x.yaml", "firmware/x.yaml ", "firmware/.git/x.yaml",
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
