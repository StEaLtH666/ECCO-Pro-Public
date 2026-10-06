#!/usr/bin/env python3
"""pub0 command line (private-side tooling for the declared public-export transition; the logic is registry/tests/_pub0_scope.py).

  generate          derive registry/tests/fixtures/pub0_manifest.json from THIS private tree (deterministic; refuses an exported
                    tree). Run it only for a deliberate new export base, review the diff, then re-pin _scope_chain.PUB0_FINGERPRINT
                    (and the PUB0 capabilities checkpoint) by hand: the tool never edits a pin.
  check             apply forward() to every target in memory and report; exit 1 on any mismatch
  diff [PATH...]    show the transform as a unified diff (Octopus values masked)
  apply --root DIR  apply forward() IN PLACE to the targets of a SEPARATE copy of the tree at DIR (for example a `git archive`
                    extract). Refuses this repository itself and refuses a DIR whose files are not the declared source.

Nothing is pushed, committed or written outside the manifest (generate) or DIR (apply).
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "registry" / "tests"))
import _pub0_scope as P  # noqa: E402


def _mask(text: str) -> str:
    return P.OCTOPUS_ID.sub(lambda m: "octopus_energy_electricity_<serial>_<mpan>_" + (m.group(3) or ""), text)


def cmd_generate(_a) -> int:
    if P.EXPORTED:
        print("refused: this tree is already the pub0 export (EXPORTED = True)", file=sys.stderr)
        return 2
    m = P.generate()
    (REPO / P.MANIFEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (REPO / P.MANIFEST_REL).write_text(P.dumps(m), encoding="utf-8", newline="\n")
    print(f"wrote {P.MANIFEST_REL}: {len(m['files'])} files, "
          f"{sum(len(s) for f in m['files'] for _n, _h, s in f['lines'])} sites, fingerprint {m['fingerprint']}")
    caps = P.records(m)["registry/inverter_capabilities.yaml"]["result_sha256"]
    print(f"pins to review by hand: _scope_chain.PUB0_FINGERPRINT = {m['fingerprint']!r}; PUB0 checkpoint (capabilities) = {caps!r}")
    return 0


def cmd_check(_a) -> int:
    bad = 0
    for rel in P.TARGETS:
        try:
            P.forward(rel, P.read_repo(rel))
        except P.Pub0Error as ex:
            bad += 1
            print(f"FAIL {rel}: {ex}")
    print(f"{len(P.TARGETS) - bad}/{len(P.TARGETS)} targets match the declared pub0 source")
    return 1 if bad else 0


def cmd_diff(a) -> int:
    for rel in a.paths or P.TARGETS:
        src = P.read_repo(rel)
        pub = P.forward(rel, src)
        sys.stdout.writelines(difflib.unified_diff(_mask(src).splitlines(True), pub.splitlines(True), f"private/{rel}", f"public/{rel}", n=0))
    return 0


def cmd_apply(a) -> int:
    root = Path(a.root).resolve()
    if root == REPO.resolve() or REPO.resolve() in root.parents:
        print("refused: apply never rewrites this repository; point --root at a separate copy", file=sys.stderr)
        return 2
    if not (root / P.SELF_REL).is_file():
        print(f"refused: {root} is not an ECCO tree (no {P.SELF_REL})", file=sys.stderr)
        return 2
    out = {}
    for rel in P.TARGETS:
        out[rel] = P.forward(rel, P.read_repo(rel, root))      # all-or-nothing: every target verified before any write
    for rel, text in out.items():
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    print(f"pub0 applied to {len(out)} files under {root}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate")
    sub.add_parser("check")
    d = sub.add_parser("diff")
    d.add_argument("paths", nargs="*")
    ap_apply = sub.add_parser("apply")
    ap_apply.add_argument("--root", required=True)
    a = ap.parse_args()
    return {"generate": cmd_generate, "check": cmd_check, "diff": cmd_diff, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
