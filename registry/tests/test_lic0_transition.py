#!/usr/bin/env python3
"""lic0 transition proofs: the v0.9.0 licence alignment of the Energy Actions card is exactly what _lic0_scope.py declares.

  [1] the declaration: five targets, each text edit present exactly once, the chain Entry lic0 has no reverter / checkpoint / delta
  [2] the bundle: as of pub0, the dist is the declared post-lic0 bytes; stripping the declared block gives the pre-lic0 bundle (the
      one the FB-B3 pins were taken on), so the code bytes are unchanged; the block carries Lit's BSD-3-Clause notices and nothing else
  [3] the folder: the pre-lic0 view of the card's Git-tracked files reproduces the FB-B3 folder pin; the post-lic0 folder is pinned
  [4] the licence declarations: all three ECCO cards say GPL-3.0-or-later; the Lit licence text ships with the frontend; both
      bundled cards keep Lit's notices (legalComments "eof")
  [5] exactness: pre_lic0_bytes refuses a missing, altered or duplicated edit / block, and is the identity elsewhere
  [6] the older suites that pin the folder route it through pre_lic0_bytes (and nothing else does)

[1]-[3] and [5] read the lic0-era files: a frozen card file (a pub0 target, or enrolled by the O3 amendment) AS OF pub0, so a
declared post-export entry (esb1: esbuild 0.28.1; ovw1: the tabbed layout) is undone exactly first; every other file, and [4], read the
live tree. [3] skips the files a post-export entry added (ovw1: src/trackSelection.ts, test/trackSelection.test.ts): neither folder pin saw them

Test-only, no network. I/O: reads repo files and `git ls-files`.
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
import _lic0_scope as L  # noqa: E402
import _pub0_scope as _pub0  # noqa: E402
import _scope_chain as sc  # noqa: E402
import _pex  # noqa: E402  (PEX, esb1: the lic0-era proofs read the frozen card files AS OF pub0; [4] reads the live files)

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
    except L.Lic0Error:
        return True
    return False


def lf(rel: str) -> bytes:
    return (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")


def lic0_era(rel: str) -> bytes:
    """`rel` (LF bytes) as lic0 left it: a frozen file AS OF pub0 (every post-export entry undone exactly), any other file live."""
    data = lf(rel)
    return _pex.as_of_pub0(rel, data.decode("utf-8")).encode("utf-8") if rel in _pex.FROZEN else data   # PEX (esb1): as of pub0


sha = L.sha
# The FB-B3 folder pin (main @ 87e6151; the three older suites pin the same value) and the folder after lic0.
FOLDER_PRE_SHA256 = "57c9798206d8a1850047474e9bdf89401523b03de89a2562a0cc18d81ac17471"
FOLDER_POST_SHA256 = "9c50fbfbce63e48222912cd2bb681e02fc2b03ab12f2d8d0003afe40c86359a9"

# ===========================================================================
print("[1] the declaration")
# ===========================================================================
check("lic0 targets are exactly the card's build script, bundle, package.json, package-lock.json and README",
      L.TARGETS == tuple(sorted(L.CARD + f for f in ("build.mjs", "dist/ecco-energy-actions-card.js", "package.json", "package-lock.json",
                                                      "README.md"))), str(L.TARGETS))
texts = {rel: _pub0.private_view_bytes(rel, lic0_era(rel)).decode("utf-8") for rel in L.TEXT_EDITS}
check("every declared text edit is present exactly once and its pre-lic0 text is absent",
      all(texts[rel].count(after) == 1 and texts[rel].count(before) == 0 for rel, eds in L.TEXT_EDITS.items() for before, after in eds))
entry = sc.CHAIN.entry("lic0")
check("the chain carries lic0 after fbd1 with no reverter, no checkpoint and no delta (it edits no chain-pinned artifact)",
      sc.CHAIN.prev_id("lic0") == "fbd1" and not entry.reverts and not entry.checkpoints and not entry.deltas
      and not entry.op_paths_changed and not entry.includes_added and entry.banned_fw_added == 0)
check("lic0 declares the two files it adds", entry.added_files == {"registry/tests/_lic0_scope.py", "registry/tests/test_lic0_transition.py"}
      and all((ROOT / f).is_file() for f in entry.added_files))

# ===========================================================================
print("")
print("[2] the bundle")
# ===========================================================================
dist = lic0_era(L.DIST)
pre = L.pre_lic0_bytes(L.DIST, dist)
block = dist[len(pre):]
check("as of pub0 the bundle is the declared post-lic0 bundle", sha(dist) == L.DIST_POST_SHA256, sha(dist))
check("stripping the declared block gives the pre-lic0 bundle exactly (the FB-B3 code bytes, unchanged)", sha(pre) == L.DIST_PRE_SHA256, sha(pre))
check("the bundle is the pre-lic0 bundle followed by exactly one appended block (no byte of the code moved)",
      dist == pre + block and len(block) == L.DIST_BLOCK_LEN and sha(block) == L.DIST_BLOCK_SHA256 and dist.count(L.DIST_BLOCK_HEAD) == 1)
btxt = block.decode("utf-8")
spdx = re.findall(r"SPDX-License-Identifier: (\S+)", btxt)
pkgs = sorted(set(re.findall(r"(?m)^(\S+?\.js):$", btxt)))
check("the block carries only BSD-3-Clause Lit notices (every SPDX id is BSD-3-Clause, every holder Google LLC)",
      spdx and set(spdx) == {"BSD-3-Clause"} and btxt.count("@license") == len(spdx)
      and set(re.findall(r"Copyright \d{4} (.+)", btxt)) == {"Google LLC"}, f"{set(spdx)} {len(spdx)}")
check("every licensed file in the block belongs to the Lit packages the bundle contains",
      pkgs and all(re.match(r"(lit-html|lit-element|@lit/reactive-element|lit)/", p) for p in pkgs), str(pkgs))
check("the block is a well-formed trailing comment", btxt.startswith("/*! Bundled license information:\n") and btxt.endswith("*/\n"))

# ===========================================================================
print("")
print("[3] the card folder")
# ===========================================================================
ls = subprocess.run(["git", "ls-files", "-z", "--", L.CARD], cwd=str(ROOT), capture_output=True)
tracked = sorted(f for f in ls.stdout.decode("utf-8").split("\0") if f)
check("the folder enumeration is the Git-tracked files only and includes every lic0 target",
      ls.returncode == 0 and set(L.TARGETS) <= set(tracked), str(len(tracked)))
f_pre, f_post = hashlib.sha256(), hashlib.sha256()
for rel in tracked:
    if rel in _pex.post_export_added():   # PEX (ovw1): a file a post-export entry added is not in the lic0-era folder (neither pin saw it)
        continue
    data = _pub0.private_view_bytes(rel, lic0_era(rel))
    f_pre.update(rel.encode())
    f_pre.update(L.pre_lic0_bytes(rel, data))
    f_post.update(rel.encode())
    f_post.update(data)
check("the pre-lic0 view of the folder reproduces the FB-B3 pin exactly (no older pin re-hashed)", f_pre.hexdigest() == FOLDER_PRE_SHA256,
      f_pre.hexdigest())
check("the folder after lic0 is pinned (the declared post-lic0 state; same recipe)", f_post.hexdigest() == FOLDER_POST_SHA256, f_post.hexdigest())

# ===========================================================================
print("")
print("[4] licence declarations")
# ===========================================================================
for card in ("ecco-energy-actions-card", "ecco-energy-flow-card", "ecco-fallback-recovery-card"):
    pj = json.loads(lf(f"frontend/{card}/package.json"))
    check(f"{card}: package.json declares GPL-3.0-or-later", pj.get("license") == "GPL-3.0-or-later", str(pj.get("license")))
    readme = lf(f"frontend/{card}/README.md").decode("utf-8")
    sect = readme.split("## License", 1)[1] if "## License" in readme else ""
    check(f"{card}: the README's License section names GPL-3.0-or-later and no MIT licence",
          "GPL-3.0-or-later" in sect and not re.search(r"\bMIT\b", sect), sect[:120])
for card in ("ecco-energy-actions-card", "ecco-energy-flow-card"):
    lock = json.loads(lf(f"frontend/{card}/package-lock.json"))
    check(f"{card}: the lockfile's root package is GPL-3.0-or-later (as package.json) and its lit packages are untouched (BSD-3-Clause)",
          lock["packages"][""]["license"] == "GPL-3.0-or-later" == json.loads(lf(f"frontend/{card}/package.json"))["license"]
          and all(lock["packages"][f"node_modules/{p}"]["license"] == "BSD-3-Clause" for p in ("lit", "lit-html", "lit-element", "@lit/reactive-element")))
mit_left = [f for f in subprocess.run(["git", "ls-files", "-z", "--", "frontend/"], cwd=str(ROOT), capture_output=True).stdout.decode().split("\0")
            if f.endswith(("package.json", "package-lock.json")) and "node_modules" not in f
            and '"license": "MIT"' in lf(f).decode("utf-8").split('"node_modules/', 1)[0]]
check("no ECCO card package or lockfile root still declares MIT", not mit_left, str(mit_left))
lit_lic = lf("frontend/LIT-LICENSE.txt").decode("utf-8")
check("frontend/LIT-LICENSE.txt is Lit's BSD 3-Clause licence (Google LLC)",
      lit_lic.startswith("BSD 3-Clause License\n\nCopyright (c) 2017 Google LLC. All rights reserved.\n")
      and "Neither the name of the copyright holder nor the names of its" in lit_lic)
for card in ("ecco-energy-actions-card", "ecco-energy-flow-card"):
    bm = lf(f"frontend/{card}/build.mjs").decode("utf-8")
    js = lf(f"frontend/{card}/dist/{card}.js").decode("utf-8")
    check(f"{card}: built with legalComments \"eof\" and its bundle carries Lit's BSD-3-Clause notices at the end",
          bm.count('legalComments: "eof"') == 1 and "legalComments: \"none\"" not in bm
          and js.count("/*! Bundled license information:") == 1 and js.rstrip().endswith("*/") and "SPDX-License-Identifier: BSD-3-Clause" in js)

# ===========================================================================
print("")
print("[5] exactness (negative controls)")
# ===========================================================================
check("a file lic0 does not touch passes through unchanged", L.pre_lic0_bytes(L.CARD + "src/config.ts", b"x\n") == b"x\n")
check("the bundle without its block is refused", raises(lambda: L.pre_lic0_bytes(L.DIST, pre)))
check("an altered block is refused", raises(lambda: L.pre_lic0_bytes(L.DIST, dist[:-6] + b"XXX*/\n")))
check("a bundle carrying the block twice is refused", raises(lambda: L.pre_lic0_bytes(L.DIST, pre + block + block)))
check("a code byte change before the block survives the reverse (so the folder pin still catches it)",
      sha(L.pre_lic0_bytes(L.DIST, b"!" + dist[1:])) != L.DIST_PRE_SHA256)
check("a text target without its edit is refused, and with the edit twice too",
      raises(lambda: L.pre_lic0_bytes(L.CARD + "package.json", b'  "license": "MIT",\n'))
      and raises(lambda: L.pre_lic0_bytes(L.CARD + "build.mjs", b'  legalComments: "eof",\n' * 2)))
check("the forward direction round-trips every target", all(
    L.post_lic0_bytes(rel, L.pre_lic0_bytes(rel, d), block) == d
    for rel, d in [(r, _pub0.private_view_bytes(r, lic0_era(r))) for r in L.TARGETS]))

# ===========================================================================
print("")
print("[6] the older folder pins")
# ===========================================================================
PINNERS = {"registry/tests/test_fallback_recovery_dashboard.py", "home-assistant/tests/test_ecco_fallback_packages.py",
           "home-assistant/tests/test_ecco_shadow_check_ux.py"}
callers = {}
for rel in subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=str(ROOT), capture_output=True).stdout.decode().split("\0"):
    if rel and rel not in ("registry/tests/_lic0_scope.py", "registry/tests/test_lic0_transition.py"):
        n = lf(rel).decode("utf-8", "replace").count("_lic0.pre_lic0_bytes(")
        if n:
            callers[rel] = n
check("exactly the three folder-pin suites call pre_lic0_bytes, once each, and their pins are the FB-B3 value",
      callers == {r: 1 for r in PINNERS} and all(lf(r).decode("utf-8").count(FOLDER_PRE_SHA256) == 1 for r in PINNERS), str(callers))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All lic0 transition checks passed.")
