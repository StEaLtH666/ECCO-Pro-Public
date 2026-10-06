#!/usr/bin/env python3
"""pub0: the declared PUBLIC-EXPORT sanitisation transition (registry/tests/_pub0_scope.py, _scope_chain.PUB0).

Test-only. No firmware build, no hardware, no Home Assistant, no network. I/O: reads repo files and the pub0 manifest.

Runs in BOTH trees. In the private development tree (EXPORTED False) the live files are pub0's SOURCE: the export is built in memory
with forward() and proven. In the public export (EXPORTED True) the live files ARE the export: the proof views are reversed exactly.

  [0] the declaration: target set, policies, manifest structure, fingerprint == _scope_chain.PUB0_FINGERPRINT, no private value in
      the manifest
  [1] mode: the tree is what EXPORTED says; private: the live tree is the declared source and the manifest is exactly what generate()
      derives from it (deterministic); public: every proof view reverses exactly and round-trips
  [2] round trip and determinism of the two directions
  [3] exactness: forward() / reverse() refuse every undeclared change (a moved / added / removed / altered site, a changed byte, a second
      Octopus value, a leftover value), and reverse() is NOT a generic replace (the un-prefixed slug the private tree already spells
      survives it; a naive replace would not reproduce the private text)
  [4] the chain entry: structure, checkpoint == the manifest, integrity of the chain ending in pub0 (in memory in the private tree,
      live in the export), and its mutations
  [5] private_view(): identity / reverse / refusal of an undeclared proof view
  [6] the PUB0 ledger: exactly the declared older-suite edits call private_view*, each commented `PUB0`
  [7] the historical hunk modules (_fbb3_ha_scope.py, _fbc3_scope.py) spell no private literal: their marker hunks bind to
      _pub0_scope.PRIVATE_SLUG at import, and the bound tuples hash to the pinned values of the hunks as generated (lossless)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import _pub0_scope as P  # noqa: E402
import _scope_chain as sc  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def notice(text: str) -> None:
    print(f"  SKIP  {text}")


def raises(fn, exc=AssertionError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


M = P.manifest()
RECS = P.records(M)
MANIFEST_TEXT = (ROOT / P.MANIFEST_REL).read_text(encoding="utf-8")
LIVE = {rel: P.read_repo(rel) for rel in P.TARGETS}
CAPS = sc.CAPABILITIES
DASH = "home-assistant/dashboards/ecco_pro.yaml"
OCTO = "home-assistant/packages/ecco_pro.yaml"
EXPORTED = P.EXPORTED

# The private and the public text of every target, whichever tree this is. The public tree has no Octopus values: its private
# representation of the Octopus file keeps the placeholders (irreversible by design).
if EXPORTED:
    PUBLIC = dict(LIVE)
    PRIVATE = {rel: P.reverse(rel, t) for rel, t in LIVE.items()}
else:
    PRIVATE = dict(LIVE)
    PUBLIC = {}
    for rel, t in LIVE.items():
        try:
            PUBLIC[rel] = P.forward(rel, t)
        except P.Pub0Error as ex:
            PUBLIC[rel] = None
            print(f"        forward({rel}): {ex}")
REAL_OCTOPUS = not EXPORTED       # the real values exist only in the private tree


def kinds_of(rel: str) -> list:
    return [k for _n, _h, sites in RECS[rel]["lines"] for _c, k in sites]


# ===========================================================================
print("[0] the declaration")
# ===========================================================================
check("TARGETS are unique, sorted, exact repo-relative POSIX paths (no glob, no prefix)",
      list(P.TARGETS) == sorted(set(P.TARGETS)) and all(sc._posix_relative_exact(p) for p in P.TARGETS))
check("KEEP_FILES, OCTOPUS_FILES and PROOF_VIEWS are targets; this module is a target; nothing is both exported and NOT_EXPORTED",
      P.KEEP_FILES <= set(P.TARGETS) and P.OCTOPUS_FILES <= set(P.TARGETS) and P.PROOF_VIEWS <= set(P.TARGETS)
      and P.SELF_REL in P.TARGETS and not set(P.NOT_EXPORTED) & set(P.TARGETS))
# PUBLIC-EXPORT: the two generated historical hunk modules no longer spell the private slug (they bind it at import, [7] below), so
# no target is a keep file any more and the public export carries exactly one private literal (the keep_prefix site of this module).
check("there are no keep files: the historical hunk modules bind the slug at import and are not pub0 targets",
      P.KEEP_FILES == frozenset() and not {"registry/tests/_fbb3_ha_scope.py", "registry/tests/_fbc3_scope.py"} & set(P.TARGETS))
check("no proof view is a keep file or carries an irreversible site (its private text is reconstructed EXACTLY)",
      all(rel not in P.KEEP_FILES and not set(kinds_of(rel)) - P.REVERSIBLE for rel in P.PROOF_VIEWS))
check("the manifest is schema ecco-pub0-manifest/1, transition pub0, and lists exactly TARGETS in order",
      M.get("schema") == P.SCHEMA and M.get("transition") == "pub0" and [f["path"] for f in M["files"]] == list(P.TARGETS))
check("the manifest fingerprint is the canonical hash of its file records and is the one pinned in _scope_chain.PUB0_FINGERPRINT",
      P.fingerprint(M["files"]) == M["fingerprint"] == sc.PUB0_FINGERPRINT, f"{P.fingerprint(M['files'])} / {sc.PUB0_FINGERPRINT}")
check("the manifest is stored in its canonical text form (P.dumps)", P.dumps(M) == MANIFEST_TEXT)
bad_struct = []
for f in M["files"]:
    prev = 0
    for n, h, sites in f["lines"]:
        if not (isinstance(n, int) and n > prev and re.fullmatch(r"[0-9a-f]{16}", h) and sites
                and [c for c, _k in sites] == sorted(c for c, _k in sites) and all(k in P.KINDS and c >= 0 for c, k in sites)):
            bad_struct.append((f["path"], n))
        prev = n
    if not (re.fullmatch(r"[0-9a-f]{64}", f["source_sha256"]) and re.fullmatch(r"[0-9a-f]{64}", f["result_sha256"])):
        bad_struct.append((f["path"], "sha"))
check("every line record is (strictly increasing line, 16-hex public-line hash, column-sorted sites of known kinds); full sha256 pairs",
      not bad_struct, str(bad_struct[:5]))
policy = []
for rel in P.TARGETS:
    ks = set(kinds_of(rel))
    if rel in P.KEEP_FILES and ks != {"keep"}:
        policy.append((rel, "keep file with a non-keep site"))
    if rel not in P.KEEP_FILES and "keep" in ks:
        policy.append((rel, "keep site outside the keep files"))
    if rel not in P.OCTOPUS_FILES and ks & set(P.OCTOPUS_SHAPE):
        policy.append((rel, "Octopus site outside the Octopus file"))
    if rel not in P.WORDING_FILES and "wording" in ks:
        policy.append((rel, "provenance-wording site outside the register map"))
    if rel not in P.ATTRIBUTION_FILES and "attribution" in ks:
        policy.append((rel, "personal-attribution site outside the register map"))
    if (rel == P.SELF_REL) != bool(ks & {"export_flag", "keep_prefix"}):
        policy.append((rel, "flag / prefix sites belong to this module only"))
check("site kinds follow the file policies (keep only in the keep files, Octopus only in ecco_pro.yaml, flag + prefix only here)", not policy, str(policy))
check("the register map carries exactly one provenance-wording site (register 214's unsupported 'Deye protocol' attribution)",
      P.WORDING_FILES == {"registry/inverter_capabilities.yaml"} and kinds_of("registry/inverter_capabilities.yaml").count("wording") == 1
      and P.PUBLIC_TOKEN["wording"] == P.WORDING_PUBLIC and "Deye" not in P.WORDING_PUBLIC and "0=Enable, 1=Disable" in P.WORDING_PUBLIC)
check("the register map carries exactly six personal-attribution sites (the six SmartDeye parity candidates), all reversible, and the "
      "public wording names no person",
      P.ATTRIBUTION_FILES == {"registry/inverter_capabilities.yaml"} and kinds_of("registry/inverter_capabilities.yaml").count("attribution") == 6
      and "attribution" in P.REVERSIBLE and P.PUBLIC_TOKEN["attribution"] == P.ATTRIBUTION_PUBLIC == "SmartDeye-listed"
      and P.attribution_name().lower() not in P.ATTRIBUTION_PUBLIC.lower()
      and P.attribution_name().lower() not in MANIFEST_TEXT.lower())
check("this module carries exactly one export_flag and one keep_prefix site, and nothing else",
      sorted(kinds_of(P.SELF_REL)) == ["export_flag", "keep_prefix"], str(kinds_of(P.SELF_REL)))
check("ecco_pro.yaml carries the three Octopus kinds and the device slug",
      set(kinds_of(OCTO)) == {"slug", "meter_serial", "import_mpan", "export_mpan"} and kinds_of(OCTO).count("meter_serial")
      == kinds_of(OCTO).count("import_mpan") + kinds_of(OCTO).count("export_mpan"))
_free_text = [k for k in M if k not in ("schema", "transition", "fingerprint", "kinds", "files")]
_free_text += [f["path"] for f in M["files"] if set(f) != {"path", "source_sha256", "result_sha256", "lines"}]
check("the manifest can carry no free text: only the fixed head keys, the fixed kind table, and per file its target path, two sha256 "
      "and (int, hash, [(int, kind)]) line records - so no private value can be in it - and it spells no private prefix / Octopus id",
      not _free_text and M["kinds"] == {k: {"public": P.PUBLIC_TOKEN[k] if k not in ("keep", "keep_prefix") else "(kept)",
                                            "reversible": k in P.REVERSIBLE} for k in P.KINDS}
      and not bad_struct and P.PRIVATE_AREA_PREFIX not in MANIFEST_TEXT and not P.OCTOPUS_ID.search(MANIFEST_TEXT), str(_free_text))
_counts = {k: sum(kinds_of(r).count(k) for r in P.TARGETS) for k in P.KINDS}
print(f"  info  {len(P.TARGETS)} targets, {sum(_counts.values())} sites: {_counts}")

# ===========================================================================
print("")
print(f"[1] mode: EXPORTED = {EXPORTED} ({'public export' if EXPORTED else 'private development tree'})")
# ===========================================================================
check("the export flag is a plain bool spelled once in this module", isinstance(EXPORTED, bool)
      and len(P.EXPORT_FLAG_LINE.findall(LIVE[P.SELF_REL])) == 1)
check("the chain carries pub0 exactly when the tree is the export", (sc.CHAIN.ids()[-1] == "pub0") == EXPORTED
      and sc.CHAIN.ids().count("pub0") == int(EXPORTED))
if not EXPORTED:
    drift = [rel for rel, t in PUBLIC.items() if t is None]
    check("PRIVATE TREE: every target is exactly the declared pub0 source (forward() accepts it). A failure here means a target changed "
          "since the manifest was generated: regenerate (tools/public/pub0.py generate), review, re-pin", not drift, str(drift))
    try:
        g1, g2 = P.generate(), P.generate()
        same = g1 == M and g1 == g2
        why = "" if same else str([f["path"] for f, h in zip(g1["files"], M["files"]) if f != h][:5])
    except P.Pub0Error as ex:
        same, why = False, str(ex)[:200]
    check("PRIVATE TREE: the committed manifest is exactly what generate() derives from this tree, and generate() is deterministic", same, why)
    check("PRIVATE TREE: the capabilities file is the root file (pub0's chain source)", sc.sha(LIVE[CAPS]) == sc.ROOT_SHA[CAPS])
    if drift:
        print(f"\nFAILED: {len(FAILURES)} check(s); the remaining sections need the export of every target and cannot run")
        sys.exit(1)
else:
    bad = []
    for rel in sorted(P.PROOF_VIEWS):
        try:
            if P.forward(rel, P.reverse(rel, LIVE[rel])) != LIVE[rel]:
                bad.append(rel)
        except P.Pub0Error as ex:
            bad.append(f"{rel}: {ex}")
    check("PUBLIC EXPORT: every proof view reverses exactly and round-trips (forward(reverse(live)) == live)", not bad, str(bad))
    check("PUBLIC EXPORT: the generator refuses an exported tree", raises(P.generate))
    check("PUBLIC EXPORT: the capabilities file is pub0's checkpoint", sc.sha(LIVE[CAPS]) == sc.PUB0.checkpoints[CAPS])

# ===========================================================================
print("")
print("[2] round trip and determinism")
# ===========================================================================
ok_pub = {rel for rel, t in PUBLIC.items() if t is not None}
rt_bad = []
for rel in sorted(ok_pub):
    pub = PUBLIC[rel]
    if sc.sha(pub) != RECS[rel]["result_sha256"]:
        rt_bad.append((rel, "result sha"))
    back = P.reverse(rel, pub)
    if sc.sha(back) != RECS[rel]["source_sha256"]:
        rt_bad.append((rel, "reverse sha"))
    if rel not in P.OCTOPUS_FILES and back != PRIVATE[rel]:
        rt_bad.append((rel, "reverse != private"))
    if (REAL_OCTOPUS or rel not in P.OCTOPUS_FILES) and P.forward(rel, PRIVATE[rel]) != pub:
        rt_bad.append((rel, "forward not deterministic"))
check("for every target: the public text hashes to the recorded result, reverse() hashes to the recorded source, reverse(forward(x)) == x "
      "(Octopus file: == x with placeholders), forward() is deterministic", not rt_bad and ok_pub == set(P.TARGETS), str(rt_bad[:5]))
vacuous = [rel for rel in P.TARGETS if rel not in P.KEEP_FILES and PUBLIC.get(rel) is not None and PUBLIC[rel] == PRIVATE[rel]]
check("every non-keep target really changes (no vacuous target); every keep file is unchanged by pub0",
      not vacuous and all(PUBLIC.get(rel) == PRIVATE[rel] for rel in P.KEEP_FILES), str(vacuous))
check("pub0 maps every file line for line (no line is added or removed)",
      all(PUBLIC[rel].count("\n") == PRIVATE[rel].count("\n") for rel in ok_pub))
self_diff = [(a, b) for a, b in zip(PRIVATE[P.SELF_REL].split("\n"), PUBLIC[P.SELF_REL].split("\n")) if a != b]
check("the export flag: forward() of this module changes exactly the one line EXPORTED = False -> EXPORTED = True",
      self_diff == [("EXPORTED = False", "EXPORTED = True")], str(self_diff))
octo_back = P.reverse(OCTO, PUBLIC[OCTO])
check("the Octopus values are irreversible by design: reverse() keeps the placeholders and the public tree spells no real value",
      not P.OCTOPUS_ID.search(PUBLIC[OCTO]) and not P.OCTOPUS_ID.search(octo_back)
      and all(octo_back.count(ph) == PUBLIC[OCTO].count(ph) > 0 for ph in P.OCTOPUS_PLACEHOLDER.values()))

# ===========================================================================
print("")
print("[3] exactness (every undeclared change is refused)")
# ===========================================================================
D_PRIV, D_PUB = PRIVATE[DASH], PUBLIC[DASH]
first = RECS[DASH]["lines"][0][0]
lines = D_PRIV.split("\n")
check("forward refuses ONE extra private-slug occurrence (coverage)", raises(lambda: P.forward(DASH, D_PRIV + f"# sensor.{P.PRIVATE_SLUG}_x\n")))
check("forward refuses a site line whose private slug was removed",
      raises(lambda: P.forward(DASH, "\n".join(lines[:first - 1] + [lines[first - 1].replace(P.PRIVATE_SLUG, P.PUBLIC_SLUG, 1)] + lines[first:]))))
check("forward refuses one changed byte away from every site (the declared source sha256)", raises(lambda: P.forward(DASH, D_PRIV.replace("views:", "views :", 1))))
check("forward refuses a moved site (one line inserted above everything)", raises(lambda: P.forward(DASH, "\n" + D_PRIV)))
check("forward / reverse refuse a file that is not a target", raises(lambda: P.forward("README.md", "x")) and raises(lambda: P.reverse("README.md", "x")))
check("forward refuses a bare private prefix that is not the slug", raises(lambda: P.forward(DASH, D_PRIV + "# " + P.PRIVATE_AREA_PREFIX + "x\n")))
pl = D_PUB.split("\n")
check("reverse refuses an altered public site line", raises(lambda: P.reverse(DASH, "\n".join(pl[:first - 1] + [pl[first - 1] + " "] + pl[first:]))))
check("reverse refuses shifted lines (its sites are positional)", raises(lambda: P.reverse(DASH, "# x\n" + D_PUB)))
check("reverse is edit-local like every chain reverter: an unrelated appended line passes through unchanged (the pins then catch it)",
      P.reverse(DASH, D_PUB + "# appended\n") == D_PRIV + "# appended\n")
bare = [m.start() for m in re.finditer(r"(?<![a-z_])" + re.escape(P.PUBLIC_SLUG), D_PRIV)]
check("hazard C.2-1 is real and handled: the private dashboard already spells the slug un-prefixed, reverse() leaves those occurrences "
      "alone, and a naive public.replace(slug, private slug) does NOT reproduce the private text",
      len(bare) >= 1 and P.reverse(DASH, D_PUB) == D_PRIV and D_PUB.replace(P.PUBLIC_SLUG, P.PRIVATE_SLUG) != D_PRIV, f"bare={len(bare)}")
if REAL_OCTOPUS:
    O = PRIVATE[OCTO]
    m0 = P.OCTOPUS_ID.search(O)
    serial, mpan = m0.group(1), m0.group(2)
    other = ("1" if mpan[-1] != "1" else "2")
    check("forward refuses a second, different value of one Octopus kind (one MPAN digit changed at one site)",
          raises(lambda: P.forward(OCTO, O[:m0.start(2)] + mpan[:-1] + other + O[m0.end(2):])))
    check("forward refuses an Octopus value surviving outside the declared sites", raises(lambda: P.forward(OCTO, O + f"# {mpan}\n")))
    check("forward refuses an undeclared extra Octopus id", raises(lambda: P.forward(OCTO, O + f"# sensor.octopus_energy_electricity_{serial}_{mpan}_x\n")))
    check("forward refuses a malformed meter serial at a site", raises(lambda: P.forward(OCTO, O[:m0.start(1)] + "zz" + O[m0.start(1) + 2:])))
else:
    notice("the Octopus forward controls need the real values, which the public export does not carry (by design)")

# ===========================================================================
print("")
print("[4] the chain entry")
# ===========================================================================
E = sc.PUB0
check("PUB0 is Entry('pub0'), the only export entry, never part of the merge-ordered ENTRIES",
      E.id == "pub0" and sc.EXPORT_ENTRIES == (E,) and "pub0" not in [e.id for e in sc.ENTRIES])
check("PUB0 edits exactly one chain-pinned artifact (the capabilities file) with a pub0 reverter, and declares nothing else",
      set(E.reverts) == set(E.checkpoints) == {CAPS} and E.reverts[CAPS].__module__ == "_pub0_scope" and not E.deltas
      and not E.op_paths_changed and not E.includes_added and not E.subst_added and not E.subst_changed and not E.subst_removed
      and not E.banned_fw_added and not E.banned_files and not E.fbh_includers and not E.tags_declared)
check("the PUB0 checkpoint is the manifest's result hash of the capabilities file, and its source hash is the chain ROOT",
      E.checkpoints[CAPS] == RECS[CAPS]["result_sha256"] and RECS[CAPS]["source_sha256"] == sc.ROOT_SHA[CAPS])
no_other = [p for p in sc.PINNED if p != CAPS and P.is_target(p)]
check("no other chain-pinned artifact is a pub0 target (firmware, headers, state machine and ha-manifest are untouched)", not no_other, str(no_other))
LIVE_PINNED = {p: sc.read_live(p) for p in sc.PINNED}
EXPORT_PINNED = dict(LIVE_PINNED) if EXPORTED else {**LIVE_PINNED, CAPS: PUBLIC[CAPS]}
CX = sc.Chain(sc.ENTRIES + sc.EXPORT_ENTRIES)
rows = sc.integrity_report(CX, EXPORT_PINNED)
check(f"the chain ending in pub0 is all green over the {'live' if EXPORTED else 'in-memory'} export ({len(rows)} rows: every checkpoint, "
      "non-identity reverters, nothing else moved, declared deltas == measured, live == root + deltas)",
      all(ok for _n, ok, _d in rows), str([(n, d) for n, ok, d in rows if not ok][:3]))
check("as of fbd1 (and as of fba) the exported capabilities file is the private root file byte for byte",
      CX.as_of(CAPS, "fbd1", EXPORT_PINNED[CAPS]) == PRIVATE[CAPS] == CX.as_of(CAPS, "fba", EXPORT_PINNED[CAPS])
      and sc.sha(PRIVATE[CAPS]) == sc.ROOT_SHA[CAPS])


def _replace(entry, **kw):
    d = {f: getattr(entry, f) for f in entry.__dataclass_fields__}
    d.update(kw)
    return sc.Entry(**d)


def _broken(chain, live) -> bool:
    return any(not ok for _n, ok, _d in sc.integrity_report(chain, live))


check("mutation: a wrong PUB0 checkpoint breaks the chain", _broken(sc.Chain(sc.ENTRIES + (_replace(E, checkpoints={CAPS: "0" * 64}),)), EXPORT_PINNED))
check("mutation: an identity PUB0 reverter is refused", _broken(sc.Chain(sc.ENTRIES + (_replace(E, reverts={CAPS: lambda t: t}),)), EXPORT_PINNED))
check("mutation: an undeclared edit to the exported capabilities file breaks the chain",
      _broken(CX, {**EXPORT_PINNED, CAPS: EXPORT_PINNED[CAPS] + "# undeclared\n"}))
check("mutation: claiming pub0 over the PRIVATE capabilities file (a false export claim) breaks the chain",
      _broken(CX, {**EXPORT_PINNED, CAPS: PRIVATE[CAPS]}))
check("mutation: an exported capabilities file WITHOUT pub0 in the chain breaks it (the export cannot hide from the chain)",
      _broken(sc.Chain(sc.ENTRIES), {**EXPORT_PINNED, CAPS: PUBLIC[CAPS]}))

# ===========================================================================
print("")
print("[5] private_view()")
# ===========================================================================
check("private_view is the identity for a file pub0 does not touch", P.private_view("README.md", "abc") == "abc"
      and P.private_view_bytes("frontend/ecco-energy-actions-card/package.json", b"x") == b"x")
check("private_view refuses a target that is not a declared proof view (in both trees)",
      raises(lambda: P.private_view("tools/ecco-snapshot.ps1", LIVE["tools/ecco-snapshot.ps1"])))
check("private_view of every proof view is the exact private text (the identity in the private tree, reverse() in the export)",
      all(P.private_view(rel, LIVE[rel]) == PRIVATE[rel] for rel in P.PROOF_VIEWS))
check("private_view_edited applies a suite's whole-line edit at the same line numbers of the private text",
      P.private_view_edited(DASH, D_PUB if EXPORTED else D_PRIV, {lines[0]: "# edited"}).split("\n")[0] == "# edited"
      and P.private_view_edited(DASH, LIVE[DASH], {}) == D_PRIV)

# ===========================================================================
print("")
print("[6] the PUB0 ledger (older suites edited by pub0, each edit commented)")
# ===========================================================================
LEDGER = {   # file -> exact number of calls of each private_view flavour
    "registry/tests/test_fallback_recovery_dashboard.py": {"private_view(": 2, "private_view_bytes(": 1, "private_view_edited(": 0},
    "home-assistant/tests/test_ecco_fallback_packages.py": {"private_view(": 2, "private_view_bytes(": 1, "private_view_edited(": 0},
    "home-assistant/tests/test_ecco_shadow_check_ux.py": {"private_view(": 1, "private_view_bytes(": 1, "private_view_edited(": 2},
}
OWN = {P.SELF_REL, "registry/tests/test_pub0_transition.py", "registry/tests/test_pub0_privacy.py", "tools/public/pub0.py",
       "registry/tests/test_lic0_transition.py"}   # lic0 (v0.9.0) proves its own transition on the private text: not an older suite
callers = {}
for d in ("registry", "home-assistant", "health", "influxdb", "tools"):
    for p in sorted((ROOT / d).rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel in OWN or "node_modules" in p.parts:
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        if "_pub0." in t:
            callers[rel] = {k: len(re.findall(r"_pub0\." + re.escape(k), t)) for k in ("private_view(", "private_view_bytes(", "private_view_edited(")}
callers.pop("registry/tests/_scope_chain.py", None)
BINDERS = ("registry/tests/_fbb3_ha_scope.py", "registry/tests/_fbc3_scope.py")     # [7]: they read _pub0.PRIVATE_SLUG only
binder_calls = {rel: callers.pop(rel, None) for rel in BINDERS}
check("exactly the declared older suites call private_view*, with exactly the declared number of calls", callers == LEDGER, str(callers))
uncommented = [(rel, i) for rel in LEDGER for i, l in enumerate(P.read_repo(rel).split("\n"), 1)
               if re.search(r"_pub0\.private_view", l) and "PUB0" not in l
               and "PUB0" not in P.read_repo(rel).split("\n")[i - 2] and "PUB0" not in P.read_repo(rel).split("\n")[i - 3]]
check("every private_view* call carries a `PUB0` comment on its line or within the two lines above", not uncommented, str(uncommented))
dash_suite = P.read_repo("registry/tests/test_fallback_recovery_dashboard.py")
check("the README / card-source privacy checks keep the private-slug ban verbatim (PUB0 edit, spec C.2 hazard 2)",
      dash_suite.count("_pub0.PRIVATE_SLUG not in readme") == 1 and dash_suite.count("_pub0.PRIVATE_SLUG not in src") == 1
      and dash_suite.count("_pub0.PRIVATE_AREA_PREFIX not in src") == 1)
check("the chain module uses pub0 only for the PUB0 entry's reverter and the export switch",
      re.findall(r"_pub0\.\w+", "\n".join(l for l in P.read_repo("registry/tests/_scope_chain.py").split("\n") if not l.lstrip().startswith("#")))
      == ["_pub0.reverter", "_pub0.EXPORTED"])

# ===========================================================================
print("")
print("[7] the historical hunk modules spell no private literal and bind losslessly")
# ===========================================================================
import json  # noqa: E402
import hashlib  # noqa: E402
import _fbb3_ha_scope as _ha3  # noqa: E402
import _fbc3_scope as _c3  # noqa: E402

# sha256 of json.dumps(tuple) of each hunk tuple AS GENERATED from the git diff (computed from the modules before the marker conversion,
# when they spelled the private slug literally 51 + 3 times). Pinned here; never re-derived from the modules under test.
BOUND_HUNKS_SHA = {
    "_fbb3_ha_scope.DASHBOARD_HUNKS": "abcb853dd28f70b3d0d551506a0a49212dd27f3d324d6116e5acde4246203596",
    "_fbb3_ha_scope.MANIFEST_HUNKS": "e04fa140ea6edf11c82d858ad7f4c85c36ed19bde709657f6a985e26f03658d8",
    "_fbb3_ha_scope.VERSION_HUNKS": "c9b065b77a3268422030f8f5c54dcd89548da8025410f3390be7a606ca68324b",
    "_fbc3_scope.DASHBOARD_HUNKS": "8afd9621cb87b2fd8387470ea080e28f6e5631a4fc72ca8086d77df53a6d82ab",
}
_bound = {"_fbb3_ha_scope.DASHBOARD_HUNKS": _ha3.DASHBOARD_HUNKS, "_fbb3_ha_scope.MANIFEST_HUNKS": _ha3.MANIFEST_HUNKS,
          "_fbb3_ha_scope.VERSION_HUNKS": _ha3.VERSION_HUNKS, "_fbc3_scope.DASHBOARD_HUNKS": _c3.DASHBOARD_HUNKS}
_got = {k: hashlib.sha256(json.dumps(v, ensure_ascii=True).encode("utf-8")).hexdigest() for k, v in _bound.items()}
check("every bound hunk tuple hashes to its pinned as-generated value (the marker conversion is lossless, in both trees)",
      _got == BOUND_HUNKS_SHA, str({k: v[:16] for k, v in _got.items() if v != BOUND_HUNKS_SHA[k]}))
check("the bound dashboard hunks carry the private slug exactly 51 (FB-B3) + 3 (FB-C3) times, as generated",
      sum(s.count(P.PRIVATE_SLUG) for h in _ha3.DASHBOARD_HUNKS for s in h) == 51
      and sum(s.count(P.PRIVATE_SLUG) for h in _c3.DASHBOARD_HUNKS for s in h) == 3)
_src = {rel: P.read_repo(rel) for rel in BINDERS}
check("neither module spells the private area prefix; each spells the marker exactly where the slug was (51 / 3)",
      all(P.PRIVATE_AREA_PREFIX not in s for s in _src.values())
      and _src[BINDERS[0]].count(_ha3.SLUG_MARK) == 51 + 1 and _src[BINDERS[1]].count(_c3.SLUG_MARK) == 3 + 1,
      str({r: s.count("@@ECCO_PRIVATE_SLUG@@") for r, s in _src.items()}))
check("the modules read pub0 only for PRIVATE_SLUG (no private_view, no other pub0 name)",
      all(re.findall(r"_pub0\.\w+", "\n".join(l for l in s.split("\n") if not l.lstrip().startswith("#"))) == ["_pub0.PRIVATE_SLUG"]
          for s in _src.values()) and all(c and not any(c.values()) for c in binder_calls.values()))
check("a hunk module with the marker left unbound would be caught (negative control: the marker is not the slug)",
      _ha3.SLUG_MARK != P.PRIVATE_SLUG and not any(_ha3.SLUG_MARK in s for h in _ha3.DASHBOARD_HUNKS for s in h))

# Informational only (never a failure, so private development never goes red for carrying site data): token-bearing tracked files
# that are neither pub0 targets nor classified NOT_EXPORTED. A later export must classify them before it can be built.
if not EXPORTED:
    try:
        ls = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True)
        tracked = [f for f in ls.stdout.decode("utf-8").split("\0") if f] if ls.returncode == 0 else []
    except OSError:
        tracked = []
    loose = []
    for rel in tracked:
        if rel in P.TARGETS or rel in P.NOT_EXPORTED:
            continue
        try:
            t = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if P.PRIVATE_AREA_PREFIX in t or P.OCTOPUS_ID.search(t):
            loose.append(rel)
    print(f"  info  token-bearing tracked files neither exported by pub0 nor classified NOT_EXPORTED: {loose or 'none'}")

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All pub0 transition checks passed.")
print("These prove the public-export sanitisation is declared, exact and reversible for the proofs; they prove nothing about hardware.")
