#!/usr/bin/env python3
"""esb1 transition proofs: the Energy Actions card builds with esbuild 0.28.1 (Dependabot PR #12, GHSA-67mh-4wv8-2f99), declared as
the post-export chain entry esb1 (registry/tests/_esb1_scope.py), appended after rtcf1.

  [0] the declaration: esb1 follows rtcf1; no chain-pinned reverter / checkpoint / delta; its frozen edits are exactly the three
      enrolled card files (O3 amendment) and the three folder-pin suites; it adds exactly its scope module and this suite; its
      fingerprint and every older one are the pinned values, and the closed pre-export record is unchanged
  [1] the bundle as of esb1 (the successor pins): its sha256; its code bytes before the licence block are lic0's pre-lic0 bundle (the
      FB-B3 code, unchanged); exactly one trailing block of the declared bytes, carrying only Lit's BSD-3-Clause notices and the same
      file -> notice map as the lic0 block
  [2] as of pub0 (esb1 undone exactly): the three card files are their enrolled 883068d state (the bundle is lic0's post-lic0 bundle);
      the three suites are their pex0 state; the suites keep the FB-B3 pin value and route the frozen card files; the card folder as
      of esb1 is pinned
  [3] the dependency change: package.json moves only the esbuild range; the lockfile moves only esbuild packages (all 0.28.1,
      registry-resolved, sha512) and the root's esbuild devDependency; Lit, TypeScript and every other package are unchanged
  [4] the security invariant (live): no tracked frontend lockfile resolves esbuild below 0.25.0 (GHSA-67mh-4wv8-2f99 is fixed in
      0.25.0) and no card's package.json allows it; THIRD_PARTY_NOTICES.md names the esbuild version and every card it bundles
  [5] exactness: the reverters round-trip and refuse an altered, undone or duplicated hunk; as of esb1 refuses an undeclared byte in
      the bundle's code, its licence block or the lockfile

Test-only. No firmware build, no hardware, no Home Assistant, no network, no npm. I/O: reads repo files and `git ls-files`.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import _esb1_scope as E  # noqa: E402
import _lic0_scope as L  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX: this suite reads the card files AS OF esb1 and AS OF pub0, so a later declared entry is undone first)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def raises(fn) -> bool:
    try:
        fn()
    except AssertionError:
        return True
    return False


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def at(rel: str, entry_id: str, text: str | None = None) -> str:
    """`rel` (LF text; the live file unless `text` is given) with every post-export entry newer than `entry_id` undone exactly."""
    live = _pex.read(rel) if text is None else text   # PEX: the live file as the suites read it
    return _pex.as_of(rel, entry_id, live)   # PEX: fails closed on any undeclared edit


CARD = "frontend/ecco-energy-actions-card/"
PKG, LOCK, DIST = E.PACKAGE_JSON_REL, E.PACKAGE_LOCK_REL, E.BUNDLE_REL
CARD_FILES = (PKG, LOCK, DIST)
SUITES = (E.SUITE_FBP_REL, E.SUITE_SCU_REL, E.SUITE_FRD_REL)
BLOCK_HEAD = "/*! Bundled license information:\n"

# The successor pins (esb1 @ public main b093aa8 + this change; LF text).
ESB1_FINGERPRINT = "ee161454359816ee40e44c04dd0c009d0b96838ba912bcf606975bcb0049d528"
# The four post-export fingerprints recorded on main before esb1, in chain order (pex0 first, rtcf1 last); an older entry can never
# be rewritten. Kept by position: each entry's own suite owns the ledger of files that name it.
OLDER_FINGERPRINTS = (
    "c91d3a5834cef6b69f692bd8c301a478138ac7627b29c53a0a0e35cac29b36f8",
    "313f73eadd0c104cd1e81f35690fac52e0b065b0eef3eed35c9718f965baeb6c",
    "46cf76256da78b24e2fd59692f0bf126eba059352c37006542708c64b38e8f8c",
    "02d4bf53955acc3788c9df5972327bb62d5af028d8b9e46e0aa872c4fc94b0a0",
)
HISTORICAL_CHAIN_SHA = "d61b7b6a231006b2913ce62733f07df562056cffd6b633b5d8035ec06217dd4e"
DIST_SHA256 = "7674bc1acc13b5a305d37b6e0055b200cbb86c172395e07cb286567a76c07d2d"
DIST_BLOCK_LEN = 1082
DIST_BLOCK_SHA256 = "c29df950c59dba048331029ac1887fe7a9db7c5433419a265a63434b00bc0093"
# The card folder as of esb1: sha256 over every Git-tracked file (repository-relative path, then its LF text as of esb1).
FOLDER_ESB1_SHA256 = "01fa0c6828c7f039c92dc5df2902727b4e69c5dbd43a70a57a92f817dce4a67c"
# The three card files' pub0 state: their sha256 (LF) at public main 883068d, restated here independently of _pex.ENROLLED.
ENROLLED_883068D = {
    PKG: "494c8c96ef80338b4613caf4f40eed1aa2bedde0220f7f2446c1751a1b57181b",
    LOCK: "aa389e0bb311846f87543eb0ca0023c87315faadad03bf5c8b7710f888a768fd",
    DIST: "c1bd37deb0dab7ad1933e5276e70388643b14b55ed57842f055eadfb1933c207",
}
FB_B3_FOLDER_PIN = "57c9798206d8a1850047474e9bdf89401523b03de89a2562a0cc18d81ac17471"
GHSA_FIXED = (0, 25, 0)   # GHSA-67mh-4wv8-2f99: esbuild <= 0.24.2 is affected, 0.25.0 is the first fixed version

CHAIN = sc.CHAIN
POST = sc.POST_EXPORT_ENTRIES
ESB1 = CHAIN.entry("esb1")

# ===========================================================================
print("[0] the declaration")
# ===========================================================================
ids = [e.id for e in POST]
check("esb1 is the fifth post-export entry, appended right after rtcf1 (the fourth; pex0 is the first)",
      "esb1" in ids and CHAIN.prev_id("esb1") == "rtcf1" and ids.index("esb1") == 4 and ids[0] == "pex0" and ids[3] == "rtcf1", str(ids))
check("esb1 carries no chain-pinned change: no reverter / checkpoint / delta / op path / include / substitution / banned token / tag",
      not ESB1.reverts and not ESB1.checkpoints and not ESB1.deltas and not ESB1.op_paths_changed and not ESB1.includes_added
      and not ESB1.subst_added and not ESB1.subst_changed and not ESB1.subst_removed and not ESB1.banned_fw_added
      and not ESB1.banned_files and not ESB1.fbh_includers and not ESB1.tags_declared and not ESB1.tags_promoted)
check("its frozen edits are exactly the three card files and the three folder-pin suites, each with its reverter and checkpoint",
      set(ESB1.frozen_reverts) == set(ESB1.frozen_checkpoints) == set(E.FROZEN_REVERTERS) == set(CARD_FILES) | set(SUITES)
      and all(ESB1.frozen_reverts[r] is E.FROZEN_REVERTERS[r] for r in E.FROZEN_REVERTERS))
check("the three card files are enrolled (owner-approved O3 amendment) at their 883068d hash, and frozen",
      all(_pex.ENROLLED.get(r) == h for r, h in ENROLLED_883068D.items()) and set(CARD_FILES) <= _pex.FROZEN)
check("the three suites are frozen (pub0 targets edited before by pex0)",
      set(SUITES) <= _pex.FROZEN and set(SUITES) == set(CHAIN.entry("pex0").frozen_reverts))
check("esb1 declares the two files it adds, and each exists",
      ESB1.added_files == E.ADDED_FILES == {"registry/tests/_esb1_scope.py", "registry/tests/test_esb1_transition.py"}
      and all((ROOT / f).is_file() for f in ESB1.added_files))
check("esb1's fingerprint is the pinned value; every older post-export fingerprint is its recorded value (none rewritten)",
      ESB1.fingerprint == ESB1_FINGERPRINT and tuple(e.fingerprint for e in POST[:4]) == OLDER_FINGERPRINTS,
      ESB1.fingerprint)
# PEX: the closed pre-export record (root, the twelve ENTRIES and pub0) hashes to its 883068d value
check("the closed pre-export chain record is unchanged", _pex.historical_chain_sha() == _pex.HISTORICAL_CHAIN_SHA == HISTORICAL_CHAIN_SHA)

# ===========================================================================
print("")
print("[1] the bundle as of esb1 (the successor pins)")
# ===========================================================================
TXT = {r: at(r, "esb1") for r in (*CARD_FILES, *SUITES)}
P0 = {r: at(r, "pub0") for r in (*CARD_FILES, *SUITES)}
dist = TXT[DIST]
i = dist.find(BLOCK_HEAD)
code, block = dist[:i], dist[i:]
check("the bundle is the declared esb1 bundle (sha256)", sha(dist) == DIST_SHA256, sha(dist))
check("its code bytes before the licence block are lic0's pre-lic0 bundle exactly (the FB-B3 code: no executable byte changed)",
      i > 0 and sha(code) == L.DIST_PRE_SHA256, sha(code))
check("exactly one licence block, at the end, of the declared length and bytes",
      dist.count(BLOCK_HEAD) == 1 and len(block.encode("utf-8")) == DIST_BLOCK_LEN and sha(block) == DIST_BLOCK_SHA256
      and block.endswith("*/\n"), f"{len(block.encode('utf-8'))} {sha(block)}")
spdx = re.findall(r"SPDX-License-Identifier: (\S+)", block)
check("the block carries only BSD-3-Clause notices of Google LLC (every SPDX id, every holder, one @license per notice)",
      bool(spdx) and set(spdx) == {"BSD-3-Clause"} and block.count("@license") == len(spdx)
      and set(re.findall(r"Copyright \d{4} (.+)", block)) == {"Google LLC"}, f"{set(spdx)} {len(spdx)}")


def notice_map(blk: str) -> dict:
    """{licensed file: its notice} of an esbuild legal-comments block (one notice may follow several files)."""
    body = blk[len(BLOCK_HEAD):].rsplit("*/", 1)[0]
    out = {}
    for group in body.strip("\n").split("\n\n"):
        lines = group.split("\n")
        files = [ln[:-1] for ln in lines if ln and not ln.startswith(" ")]
        notice = "\n".join(ln for ln in lines if ln.startswith(" "))
        for f in files:
            out[f] = notice
    return out


old_dist = P0[DIST]
old_block = old_dist[old_dist.find(BLOCK_HEAD):]
m_new, m_old = notice_map(block), notice_map(old_block)
check("the same Lit files carry the same notices as in the lic0 block (esbuild 0.28.1 only groups identical notices)",
      len(m_new) == 15 and m_new == m_old and all(re.match(r"(lit-html|lit-element|@lit/reactive-element|lit)/", f) for f in m_new),
      f"{len(m_new)} vs {len(m_old)}")

# ===========================================================================
print("")
print("[2] as of pub0 (esb1 undone exactly)")
# ===========================================================================
check("as of pub0 the three card files are their enrolled 883068d state, byte for byte",
      all(sha(P0[r]) == h for r, h in ENROLLED_883068D.items()), str({r: sha(P0[r])[:16] for r in CARD_FILES}))
check("as of pub0 the bundle is lic0's declared post-lic0 bundle: the same code followed by the lic0 block",
      sha(P0[DIST]) == L.DIST_POST_SHA256 and P0[DIST].encode("utf-8") == code.encode("utf-8") + old_block.encode("utf-8")
      and len(old_block.encode("utf-8")) == L.DIST_BLOCK_LEN and L.sha(old_block.encode("utf-8")) == L.DIST_BLOCK_SHA256)
check("no post-export entry before esb1 edits the card files (as of rtcf1 == as of pub0)",
      all(at(r, "rtcf1") == P0[r] for r in CARD_FILES))
pex0 = CHAIN.entry("pex0")
check("as of rtcf1 the three suites are exactly their pex0 state (esb1 is the only later edit to them)",
      all(sha(at(r, "rtcf1")) == pex0.frozen_checkpoints[r] for r in SUITES))
check("each suite keeps the FB-B3 folder pin value (nothing re-hashed) and routes a frozen card file as of pub0",
      all(TXT[r].count(FB_B3_FOLDER_PIN) == 1 and TXT[r].count("if rel in _pex.FROZEN else _fe_lf") == 1
          and TXT[r].count("pre_lic0_bytes(") == 1 for r in SUITES))   # still exactly one lic0 call (lic0's own [6] names the callers)
tracked = sorted(f for f in subprocess.run(["git", "ls-files", "-z", "--", CARD], cwd=str(ROOT), capture_output=True)
                 .stdout.decode("utf-8").split("\0") if f)
folder = hashlib.sha256()
esb1_files = [f for f in tracked if f not in _pex.post_export_added()]   # PEX (ovw1): files a later entry added were not in the folder as of esb1
for rel in esb1_files:
    folder.update(rel.encode())
    folder.update((TXT[rel] if rel in TXT else at(rel, "esb1") if rel in _pex.FROZEN else (ROOT / rel).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")).encode("utf-8"))   # PEX (ovw1): a frozen card file AS OF esb1
check("the card folder as of esb1 is pinned (26 Git-tracked files: path and LF text)", len(esb1_files) == 26 and set(CARD_FILES) <= set(esb1_files)
      and folder.hexdigest() == FOLDER_ESB1_SHA256, folder.hexdigest())

# ===========================================================================
print("")
print("[3] the dependency change")
# ===========================================================================
pj, pj0 = json.loads(TXT[PKG]), json.loads(P0[PKG])
check("package.json: only the esbuild devDependency range moves, ^0.21.5 -> ^0.28.1",
      pj0["devDependencies"]["esbuild"] == "^0.21.5" and pj["devDependencies"]["esbuild"] == "^0.28.1"
      and {**pj, "devDependencies": {**pj["devDependencies"], "esbuild": "^0.21.5"}} == pj0)
lk, lk0 = json.loads(TXT[LOCK]), json.loads(P0[LOCK])
pk, pk0 = lk["packages"], lk0["packages"]
eb = sorted(k for k in pk if k == "node_modules/esbuild" or k.startswith("node_modules/@esbuild/"))
moved = sorted(k for k in set(pk) | set(pk0) if pk.get(k) != pk0.get(k))
check("the lockfile moves only the root's esbuild devDependency and esbuild packages; nothing else is touched",
      {k: v for k, v in lk.items() if k != "packages"} == {k: v for k, v in lk0.items() if k != "packages"}
      and set(moved) <= {""} | set(eb) | {k for k in pk0 if "esbuild" in k}
      and {**pk[""], "devDependencies": {**pk[""]["devDependencies"], "esbuild": "^0.21.5"}} == pk0[""], str(moved[:6]))
check("every esbuild package is 0.28.1, resolved from registry.npmjs.org with a sha512 integrity",
      len(eb) == 27 and all(pk[k]["version"] == "0.28.1" and pk[k]["resolved"].startswith("https://registry.npmjs.org/")
                            and pk[k]["integrity"].startswith("sha512-") for k in eb))
check("esbuild's optional platform packages are exactly the locked ones, all 0.28.1 (three new: netbsd-arm64, openbsd-arm64, "
      "openharmony-arm64; none removed)",
      set(pk["node_modules/esbuild"]["optionalDependencies"].values()) == {"0.28.1"}
      and {"node_modules/" + n for n in pk["node_modules/esbuild"]["optionalDependencies"]} == set(eb) - {"node_modules/esbuild"}
      and sorted(set(pk) - set(pk0)) == ["node_modules/@esbuild/netbsd-arm64", "node_modules/@esbuild/openbsd-arm64",
                                         "node_modules/@esbuild/openharmony-arm64"] and not set(pk0) - set(pk))
check("Lit, TypeScript and the root's licence are unchanged (lit 3.3.3, lit-html 3.3.3, lit-element 4.2.2, @lit/reactive-element "
      "2.1.2, typescript 5.9.3, GPL-3.0-or-later)",
      [pk[f"node_modules/{n}"]["version"] for n in ("lit", "lit-html", "lit-element", "@lit/reactive-element", "typescript")]
      == ["3.3.3", "3.3.3", "4.2.2", "2.1.2", "5.9.3"] and pk[""]["license"] == "GPL-3.0-or-later" == pj["license"])

# ===========================================================================
print("")
print("[4] the security invariant (live)")
# ===========================================================================


def version(v: str) -> tuple:
    m = re.fullmatch(r"[\^~]?(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        raise AssertionError(f"not a plain esbuild version or caret / tilde range: {v!r}")
    return tuple(int(x) for x in m.groups())


tracked_all = [f for f in subprocess.run(["git", "ls-files", "-z", "--", "frontend/"], cwd=str(ROOT), capture_output=True)
               .stdout.decode("utf-8").split("\0") if f]
locks = sorted(f for f in tracked_all if f.endswith("/package-lock.json"))
pkgs = sorted(f for f in tracked_all if f.endswith("/package.json"))
resolved, low = {}, []
for f in locks:
    for k, v in json.loads((ROOT / f).read_text(encoding="utf-8"))["packages"].items():
        if k == "node_modules/esbuild" or k.endswith("/node_modules/esbuild"):
            resolved[f] = v["version"]
            if version(v["version"]) < GHSA_FIXED:
                low.append((f, k, v["version"]))
specs = {}
for f in pkgs:
    dd = json.loads((ROOT / f).read_text(encoding="utf-8")).get("devDependencies", {})
    if "esbuild" in dd:
        specs[f] = dd["esbuild"]
check("no tracked frontend lockfile resolves esbuild below 0.25.0 (GHSA-67mh-4wv8-2f99)", bool(resolved) and not low, str(low))
check("no card's package.json allows an esbuild below 0.25.0, and every card that declares esbuild has a lockfile resolving it",
      all(version(s) >= GHSA_FIXED for s in specs.values())
      and {f.rsplit("/", 1)[0] for f in specs} == {f.rsplit("/", 1)[0] for f in resolved}, f"{specs} {resolved}")
check("the Energy Actions card itself resolves esbuild 0.28.1", resolved.get(LOCK) == "0.28.1", str(resolved.get(LOCK)))
notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
row = [ln for ln in notices.split("\n") if ln.startswith("| esbuild |")]
check("THIRD_PARTY_NOTICES.md has one esbuild row naming exactly the versions the lockfiles resolve and every card that bundles with it",
      len(row) == 1 and set(re.findall(r"\b0\.\d+\.\d+\b", row[0])) == set(resolved.values())
      and all(f.split("/")[1] in row[0] for f in resolved), str(row))

# ===========================================================================
print("")
print("[5] exactness and negative controls")
# ===========================================================================
roundtrip = {"package.json": E.add_esb1_package_json, "package-lock.json": E.add_esb1_package_lock, "bundle": E.add_esb1_bundle,
             "fallback_packages": E.add_esb1_fallback_packages_suite, "shadow_check_ux": E.add_esb1_shadow_check_ux_suite,
             "fallback_recovery_dashboard": E.add_esb1_fallback_recovery_dashboard_suite}
pairs = dict(zip(roundtrip, (*CARD_FILES, *SUITES)))
check("every esb1 reverter round-trips: applying its pairs to the text as of rtcf1 gives the text as of esb1",
      all(fn(at(pairs[k], "rtcf1")) == TXT[pairs[k]] for k, fn in roundtrip.items()))
bad = []
for rel, fn in E.FROZEN_REVERTERS.items():
    for before, after in fn.edits:
        k = len(after) // 2
        for m in (TXT[rel].replace(after, after[:k] + ("~" if after[k] != "~" else "^") + after[k + 1:], 1),
                  TXT[rel].replace(after, before, 1), TXT[rel] + after):
            if not raises(lambda m=m, fn=fn: fn(m)):
                bad.append(rel)
check("every reverter refuses each of its hunks altered by one character, already undone, or duplicated", not bad, str(sorted(set(bad))))
check("reading the bundle as of an earlier entry refuses one changed byte in its code (it is no declared state)",
      raises(lambda: at(DIST, "pub0", ("!" + dist[1:]))))
check("...and an altered licence notice, and a second licence block",
      raises(lambda: at(DIST, "pub0", dist.replace("Copyright 2021 Google LLC", "Copyright 2021 Google LLX", 1)))
      and raises(lambda: at(DIST, "pub0", dist + block)))
check("...and an undeclared lockfile change (one more byte), and a package.json that still says ^0.21.5",
      raises(lambda: at(LOCK, "pub0", TXT[LOCK] + " ")) and raises(lambda: at(PKG, "pub0", P0[PKG])))
check("esb1's bundle reverter refuses the lic0-era bundle (its block is not esb1's)", raises(lambda: E.pre_esb1_bundle(P0[DIST])))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All esb1 transition checks passed.")
print("These prove that the esbuild 0.28.1 upgrade of the Energy Actions card is declared, exact and reversible, that its executable "
      "code is unchanged and its licence notices kept, and that no tracked card resolves a vulnerable esbuild; they prove nothing "
      "about hardware.")
