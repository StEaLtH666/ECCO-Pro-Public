#!/usr/bin/env python3
"""Regression: the static-pin base of the fbb2 entry (test_fallback_save_static_pins.py) is derived correctly when the historical private commit is ABSENT.

_fbb2_static_lib.base_text() first asks git for the firmware as of fbb1 (`git show 65e4be5:<fw>`, then `git show HEAD:<fw>`)
and accepts a candidate ONLY if its sha256 is the scope chain's pinned fbb1 checkpoint. In a clone without that commit (a fresh
public history, a shallow clone, a git-less tarball) it falls back to the chain. It used to call
`CHAIN.as_of(fw, "fbb1", <text>)` on the text the suite hands it - live_text(), the firmware AS OF fbb2 - which undoes every
entry newer than fbb1, so the FB-C2 / FB-D1 reverters ran on a text that never had their edits and raised: the static-pin suite
failed on day one of any fresh history. The fix undoes only the entries after fbb1 up to fbb2.

Test-only, no firmware build, no hardware. I/O: reads repo files; [4] copies the git-tracked firmware / registry / tools files
into a TemporaryDirectory, makes a brand-new single-commit git repo there and runs the library in it.

  [1] root cause, pinned: the old full-chain expression cannot reproduce the fbb1 base from the fbb2 text
  [2] historical commit ABSENT (git answers "bad object"): live_text() and base_text() come from the chain, hash-verified
  [3] git missing entirely: same result; the hash pin still refuses a forged base
  [4] a REAL fresh git history (new repo, one commit, no 65e4be5 / 87e6151): the library derives the same verified base
  [5] private history (when 65e4be5 is present): git is still preferred and the chain text equals it byte for byte
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import _fbb2_static_lib as L  # noqa: E402

FAILURES: list[str] = []
CH = L.chain.CHAIN


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def notice(text: str) -> None:
    print(f"  SKIP  {text}")


class _GitAbsent:
    """Stand-in for subprocess.run inside the library: every `git show` behaves as in a clone without the object."""

    def __init__(self, missing_binary: bool = False):
        self.missing_binary = missing_binary
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if self.missing_binary:
            raise FileNotFoundError("git")
        return subprocess.CompletedProcess(argv, 128, b"", b"fatal: invalid object name\n")


def with_fake_git(fake, fn):
    real = L.subprocess.run
    L.subprocess.run = fake
    try:
        return fn()
    finally:
        L.subprocess.run = real


FW = L.FW_REL
WANT_FBB1 = CH.checkpoint(FW, "fbb1")
WANT_FBB2 = CH.checkpoint(FW, "fbb2")
DISK = L.FW_PATH.read_text(encoding="utf-8")
FBB2_TEXT = CH.as_of(FW, "fbb2", DISK)

print("[1] root cause")
newer = [e.id for e in CH.after("fbb2") if FW in e.reverts]
check("there is at least one chain entry newer than fbb2 that edits the firmware (else [1] would be vacuous)", bool(newer), str(newer))
try:
    _old = CH.as_of(FW, "fbb1", FBB2_TEXT)
    old_ok = L.chain.sha(_old) == WANT_FBB1
    old_err = ""
except AssertionError as ex:
    old_ok, old_err = False, str(ex)[:120]
check("the pre-fix expression CHAIN.as_of(fw, 'fbb1', <fbb2 text>) does NOT yield the fbb1 base (it applies newer reverters to "
      "a text that never had their edits)", not old_ok, old_err)
check("the as-of-fbb2 text is the pinned fbb2 checkpoint", L.chain.sha(FBB2_TEXT) == WANT_FBB2)
check("the chain truncated at fbb2 undoes exactly the fbb2 entry: its fbb1 view of the fbb2 text is the pinned fbb1 checkpoint",
      L.chain.sha(L.chain.Chain(CH.upto("fbb2")).as_of(FW, "fbb1", FBB2_TEXT)) == WANT_FBB1)

print("")
print("[2] historical private commit ABSENT (git answers 'invalid object')")
fake = _GitAbsent()
live = with_fake_git(fake, L.live_text)
base, src, why = with_fake_git(fake, lambda: L.base_text(live))
check("live_text() falls back to the chain and returns the pinned fbb2 state", L.chain.sha(live) == WANT_FBB2)
check("base_text() derives the base from the chain fbb1 reverter, hash-verified against the pinned fbb1 checkpoint",
      base is not None and src == "chain fbb1 reverter" and L.chain.sha(base) == WANT_FBB1, f"src={src!r} why={why!r}")
check("both historical commits and HEAD were asked for first (git is still preferred when it can answer)",
      [c[2] for c in fake.calls if c[:2] == ["git", "show"]] == [f"{L.FBB2_COMMIT}:{FW}", f"{L.BASE_COMMIT}:{FW}", f"HEAD:{FW}"],
      str(fake.calls))
real_cp = L.base_checkpoint
L.base_checkpoint = lambda: "0" * 64
try:
    forged = with_fake_git(_GitAbsent(), lambda: L.base_text(live))
finally:
    L.base_checkpoint = real_cp
check("negative control: with a wrong pinned checkpoint the chain candidate is REFUSED (no base, a reason given)",
      forged[0] is None and "sha mismatch" in forged[2], forged[2])
check("negative control: a text that is not the fbb2 state yields no base (the fbb2 reverter is exact)",
      with_fake_git(_GitAbsent(), lambda: L.base_text(FBB2_TEXT + "# not fbb2\n"))[0] is None)

print("")
print("[3] git not installed at all")
fake2 = _GitAbsent(missing_binary=True)
live2 = with_fake_git(fake2, L.live_text)
base2, src2, why2 = with_fake_git(fake2, lambda: L.base_text(live2))
check("same verified base when the git binary is missing (OSError is a miss, never a crash)",
      live2 == live and base2 == base and src2 == "chain fbb1 reverter", f"src={src2!r} why={why2!r}")

print("")
print("[4] a REAL fresh git history")


def _git(*args, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True)


try:
    ls = _git("ls-files", "-z", "--", "firmware", "registry", "tools", cwd=ROOT)
except OSError:
    ls = None
if ls is None or ls.returncode != 0:
    notice("git is not available here: the real fresh-history run cannot be built ([2]/[3] still prove the fallback)")
else:
    files = [f for f in ls.stdout.decode("utf-8").split("\0") if f]
    with tempfile.TemporaryDirectory(prefix="ecco_fresh_") as d:
        dst = Path(d)
        for rel in files:
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, target)
        ident = ["-c", "user.name=fresh", "-c", "user.email=fresh@example.invalid", "-c", "core.autocrlf=false",
                 "-c", "commit.gpgsign=false"]
        ok_init = (_git("init", "-q", cwd=dst).returncode == 0 and _git(*ident, "add", "-A", cwd=dst).returncode == 0
                   and _git(*ident, "commit", "-q", "-m", "fresh history", cwd=dst).returncode == 0)
        check("a brand-new repository with one commit was created from the tracked files", ok_init)
        absent = [_git("cat-file", "-e", f"{c}^{{commit}}", cwd=dst).returncode != 0 for c in (L.BASE_COMMIT, L.FBB2_COMMIT)]
        check("neither historical commit exists in it (65e4be5, 87e6151)", all(absent), str(absent))
        probe = (
            "import json, sys; sys.path.insert(0, 'registry/tests'); import _fbb2_static_lib as L;"
            "t = L.live_text(); b, s, w = L.base_text(t);"
            "print(json.dumps({'live': L.chain.sha(t), 'base': b and L.chain.sha(b), 'src': s, 'why': w}))"
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run([sys.executable, "-c", probe], cwd=str(dst), capture_output=True, env=env, timeout=600)
        try:
            out = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
        except (ValueError, IndexError):
            out = {}
        check("in the fresh repo the library returns the pinned fbb2 state and the chain-derived, hash-verified fbb1 base",
              r.returncode == 0 and out.get("live") == WANT_FBB2 and out.get("base") == WANT_FBB1 and out.get("src") == "chain fbb1 reverter",
              f"rc={r.returncode} out={out} err={r.stderr.decode('utf-8', 'replace')[-300:]}")

print("")
print("[5] private history still preferred")
have = subprocess.run(["git", "cat-file", "-e", f"{L.BASE_COMMIT}^{{commit}}"], cwd=str(ROOT), capture_output=True).returncode == 0 \
    if shutil.which("git") else False
if not have:
    notice(f"commit {L.BASE_COMMIT} is not in this clone (fresh history): the git-preferred path cannot be exercised here")
else:
    gb, gsrc, gwhy = L.base_text(L.live_text())
    check(f"with the private history present the base comes from git {L.BASE_COMMIT} and is hash-verified",
          gb is not None and gsrc == f"git {L.BASE_COMMIT}" and L.chain.sha(gb) == WANT_FBB1, f"src={gsrc!r} why={gwhy!r}")
    check("the chain-derived base is byte-identical to the git one", gb == base)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All fresh-history fallback checks passed.")
