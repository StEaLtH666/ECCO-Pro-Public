#!/usr/bin/env python3
"""PEX: the POST-EXPORT EDIT LAYER (registry/tests/_pex.py, schema ecco-pex/1) and its foundation entry pex0 (_pex0_scope.py).

Test-only. No firmware build, no hardware, no Home Assistant, no network. I/O: reads repo files and `git ls-files`.

  [0]  the declaration: schema, the frozen set (the pub0 targets that are not chain-pinned, plus ENROLLED = VERSION.yaml only), the
       deny-list, the chain shape (the twelve closed ENTRIES, then pub0, then the post-export entries), pex0 carries no product change
  [1]  T1 exactness: every post-export hunk (and the gate's) is exact - one altered character, a missing or a duplicated hunk raises
  [2]  T2 checkpoints: every entry reproduces its recorded checkpoints; undoing it lands on the declared state before it
  [3]  T3 nothing else moved: at every post-export state every frozen and chain-pinned file is exactly its declared state
  [4]  T4 live == the newest declared state; as_of_pub0 reconstructs the 57 pub0 target result hashes byte for byte (and the enrolled
       file and the chain-pinned artifacts their pub0 state); it refuses an undeclared file
  [5]  T5 privacy: no post-export hunk, gate hunk or file a post-export entry adds spells a private literal
  [6]  T6 immutability: the deny-list, the deny-listed files byte-identical to 883068d, the closed pre-export chain record, and the
       MANDATORY post-pex0 hash pin of the PUB0 gate (test_pub0_transition.py)
  [7]  T7 fingerprints: every post-export fingerprint is the hash of its record, hash-linked to pub0's (pex0's pinned)
  [8]  T8 the PEX ledger: exactly the declared older-suite reads call _pex, each commented `PEX`
  [9]  T9 the whole chain (root -> ENTRIES -> pub0 -> post-export) passes _scope_chain.integrity_report on the live tree
  [10] adversarial mutations: every one of them must be refused
  [11] SYNTHETIC E1-E3 (in memory, anchored as of pex0): a dashboard wording edit (E1), a line inserted at the top of a frozen package (E2) and a 12th
       package stanza in the chain-pinned manifest (E3) - undeclared, each is refused; declared as one post-export entry, every PEX
       proof, the chain and the routed historical pins hold, and the files AS OF pub0 are the pub0 export byte for byte
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import yaml  # noqa: E402

import _fbb3_ha_scope as ha3  # noqa: E402
import _fbc3_scope as c3  # noqa: E402
import _pex as X  # noqa: E402
import _pex0_scope as X0  # noqa: E402
import _pub0_scope as _pub0  # noqa: E402
import _scope_chain as sc  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def raises(fn, exc=AssertionError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def all_ok(rows) -> bool:
    return bool(rows) and all(ok for _n, ok, _d in rows)


def failing(rows) -> list:
    return [(n, d) for n, ok, d in rows if not ok]


DASH = "home-assistant/dashboards/ecco_pro.yaml"
TELEMETRY = "home-assistant/packages/ecco_canonical_telemetry.yaml"
VERSION = "VERSION.yaml"
MANIFEST = sc.HA_MANIFEST
CAPS = sc.CAPABILITIES
RECS = _pub0.records()
POST = X.post_export()
PRE = sc.ENTRIES + sc.EXPORT_ENTRIES
HISTORICAL_IDS = ["fba", "mtou1", "dump_v2", "fbc1", "fbb0", "fbb1", "fbb2", "fbb3", "fbc2", "fbc3", "fbd1", "lic0"]
PEX0_FINGERPRINT = "c91d3a5834cef6b69f692bd8c301a478138ac7627b29c53a0a0e35cac29b36f8"
# The MANDATORY post-pex0 pin of the PUB0 gate (owner hardening): sha256 (LF) of registry/tests/test_pub0_transition.py after pex0, and
# at public main @ 883068d. Re-pinned only by an explicitly reviewed governance change that says why, never to make a test pass.
PUB0_GATE_SHA256 = "e007b1ec5a65a45682d09a403898f9170e2c0fff26ea180af0c6317efda6ef3e"
PUB0_GATE_BASE_SHA256 = "2d430905d66f846e57714fdd87ffa43bf167f9a9f44482b027f63437a8b2c001"
LIVE = {rel: X.read(rel) for rel in sorted(X.FROZEN | set(sc.PINNED))}

# ===========================================================================
print("[0] the declaration")
# ===========================================================================
check("this tree is the pub0 export (PEX is public-tree-only, owner decision O5)", _pub0.EXPORTED is True)
check("schema ecco-pex/1; the genesis is pub0 of public main @ 883068d",
      X.SCHEMA == "ecco-pex/1" and X.EXPORT_ID == sc.PUB0.id == "pub0" and X.BASE_COMMIT == "883068daf63e51ff0e79c9f2cc427a3124f6cccb")
check("ENROLLED is exactly VERSION.yaml (owner decision O3), a 64-hex hash, neither a pub0 target nor chain-pinned",
      set(X.ENROLLED) == {VERSION} and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in X.ENROLLED.values())
      and not set(X.ENROLLED) & set(_pub0.TARGETS) and not set(X.ENROLLED) & set(sc.PINNED))
check("FROZEN is exactly the pub0 targets that are not chain-pinned, plus ENROLLED (56 + 1 files)",
      X.FROZEN == (frozenset(_pub0.TARGETS) - frozenset(sc.PINNED)) | frozenset(X.ENROLLED) and len(X.FROZEN) == 57
      and set(_pub0.TARGETS) & set(sc.PINNED) == {CAPS})
_scopes_now = set(subprocess.run(["git", "ls-files", "-z", "--", "registry/tests/_*_scope.py"], cwd=str(ROOT), capture_output=True)
                  .stdout.decode("utf-8").split("\0")) - {""}
_post_added = set().union(set(), *(e.added_files for e in POST))
check("DENY is the pub0 module, its manifest and every scope module of 883068d; every tracked scope module is deny-listed or added by a "
      "post-export entry", X.DENY == frozenset(X.DENY_SHA) and len(X.DENY) == 16 and {_pub0.SELF_REL, _pub0.MANIFEST_REL} <= X.DENY
      and _scopes_now and _scopes_now == (X.DENY - {_pub0.MANIFEST_REL}) | {f for f in _post_added if f.endswith("_scope.py")},
      str(sorted(_scopes_now ^ ((X.DENY - {_pub0.MANIFEST_REL}) | _post_added))))
check("the chain is the twelve closed merge-ordered ENTRIES, then pub0, then exactly POST_EXPORT_ENTRIES (pex0 first)",
      [e.id for e in sc.ENTRIES] == HISTORICAL_IDS and sc.CHAIN.ids() == HISTORICAL_IDS + ["pub0"] + [e.id for e in sc.POST_EXPORT_ENTRIES]
      and POST == sc.POST_EXPORT_ENTRIES and POST[0].id == "pex0", str(sc.CHAIN.ids()[-4:]))
E0 = sc.CHAIN.entry("pex0")
check("pex0 is the foundation and carries no product change: no chain-pinned reverter / checkpoint / delta / op path / include / "
      "substitution / banned token / tag; its frozen edits are exactly the three routed suites (test files)",
      not E0.reverts and not E0.checkpoints and not E0.deltas and not E0.op_paths_changed and not E0.includes_added
      and not E0.subst_added and not E0.subst_changed and not E0.subst_removed and not E0.banned_fw_added and not E0.banned_files
      and not E0.fbh_includers and not E0.tags_declared and not E0.tags_promoted
      and set(E0.frozen_reverts) == set(E0.frozen_checkpoints) == set(X0.FROZEN_EDITS) == {
          "registry/tests/test_fallback_recovery_dashboard.py", "home-assistant/tests/test_ecco_fallback_packages.py",
          "home-assistant/tests/test_ecco_shadow_check_ux.py"})
check("pex0 declares the four files it adds (the layer, its routing data, this suite, the documentation page) and each exists",
      E0.added_files == X0.ADDED_FILES == {"registry/tests/_pex.py", "registry/tests/_pex0_scope.py", "registry/tests/test_pex_transition.py",
                                           "docs/dev/post-export-edit-layer.md"} and all((ROOT / f).is_file() for f in E0.added_files))
check("pex0's frozen reverters are _pex0_scope's, one per routed suite", all(fn.__module__ == "_pex0_scope" for fn in E0.frozen_reverts.values()))
check("post_export_added() is exactly the union of the post-export entries' declared added files (pex0's four today)",
      X.post_export_added() == frozenset().union(frozenset(), *(e.added_files for e in POST)) and E0.added_files <= X.post_export_added()
      and X.post_export_added(sc.Chain(sc.ENTRIES)) == frozenset())

# ===========================================================================
print("")
print("[1] T1 exactness (every post-export hunk, and the gate's)")
# ===========================================================================
ROWS = X.report()


def pub0_of(rel: str, text: str, chain=None):
    """as_of_pub0, or None when it refuses (an undeclared edit): reported as a FAIL below, never a crash."""
    try:
        return X.as_of_pub0(rel, text, chain)
    except AssertionError:
        return None


STATES = {POST[-1].id: dict(LIVE)}
try:
    for _e in reversed(POST):
        _cur = STATES[_e.id]
        STATES[sc.CHAIN.prev_id(_e.id)] = {**_cur, **{rel: fn(_cur[rel]) for rel, fn in (*_e.reverts.items(), *_e.frozen_reverts.items())}}
    _states_ok = True
except AssertionError as _ex:
    _states_ok = False
    _states_err = f"{type(_ex).__name__}: {str(_ex)[:200]}"
check("the post-export reverters apply to the live files (else the PEX report below names the undeclared edit)", _states_ok,
      "" if _states_ok else _states_err)


def hunk_mutants(text: str, edits) -> list:
    """For every (before, after) pair: one character altered in its `after`, the pair already undone, the `after` duplicated."""
    out = []
    for before, after in edits:
        k = len(after) // 2
        out.append(text.replace(after, after[:k] + ("~" if after[k] != "~" else "^") + after[k + 1:], 1))
        out.append(text.replace(after, before, 1))
        out.append(text + after)
    return out


_t1_bad = [] if _states_ok else ["(the reverters do not apply to the live files)"]
for _e in POST if _states_ok else ():
    for rel, fn in _e.frozen_reverts.items():
        for m in hunk_mutants(STATES[_e.id][rel], fn.edits):
            if not raises(lambda m=m, fn=fn: fn(m)):
                _t1_bad.append((_e.id, rel))
check("every frozen reverter raises on each of its hunks altered by one character, already undone, or duplicated", not _t1_bad, str(_t1_bad[:3]))
_gate = X.read(X0.GATE_REL)
check("the gate's routing hunks are exact in the same way",
      all(raises(lambda m=m: X0.pre_pex0_gate(m)) for m in hunk_mutants(_gate, X0.GATE_EDITS)))
check("the frozen reverters undo exactly their own hunks and round-trip (apply(undo(x)) == x)",
      _states_ok and all(X0.apply(fn(STATES[_e.id][rel]), fn.edits, rel) == STATES[_e.id][rel] for _e in POST for rel, fn in _e.frozen_reverts.items()))

# ===========================================================================
print("")
print("[2] T2 checkpoints / [3] T3 nothing else moved / [7] T7 fingerprints (the PEX report)")
# ===========================================================================
for name, ok, detail in ROWS:
    check(name, ok, detail)

# ===========================================================================
print("")
print("[4] T4 live == the newest declared state; as_of_pub0 reconstructs the pub0 export")
# ===========================================================================
_P0 = {rel: pub0_of(rel, LIVE[rel]) for rel in LIVE}
_rec_bad = [rel for rel in _pub0.TARGETS if _P0[rel] is None or X.sha(_P0[rel]) != RECS[rel]["result_sha256"]]
check(f"as_of_pub0 reconstructs every one of the {len(_pub0.TARGETS)} pub0 targets byte for byte: its sha256 is the manifest's result_sha256",
      len(_pub0.TARGETS) == 57 and not _rec_bad, str(_rec_bad[:5]))
check("as_of_pub0 reconstructs the enrolled file's 883068d hash and every chain-pinned artifact's pub0 checkpoint",
      all(_P0[rel] is not None and X.sha(_P0[rel]) == X.base(rel) for rel in [*X.ENROLLED, *sc.PINNED])
      and X.base(MANIFEST) == sc.CHAIN.checkpoint(MANIFEST, "fbb3") and X.base(CAPS) == sc.PUB0.checkpoints[CAPS] == RECS[CAPS]["result_sha256"],
      str([rel for rel in [*X.ENROLLED, *sc.PINNED] if _P0[rel] is None or X.sha(_P0[rel]) != X.base(rel)]))
_edited = set().union(set(), *(set(e.frozen_reverts) | set(e.reverts) for e in POST))
check("as_of_pub0 is the identity for every frozen file no post-export entry edits (the export itself)",
      all(_P0[rel] == LIVE[rel] for rel in X.FROZEN - _edited), str([rel for rel in X.FROZEN - _edited if _P0[rel] != LIVE[rel]][:5]))
check("as_of_pub0 refuses a file that is neither frozen nor chain-pinned (README.md, a firmware header) - no silent identity",
      raises(lambda: X.as_of_pub0("README.md", X.read("README.md"))) and raises(lambda: X.as_of_pub0("firmware/include/ecco_rtc_policy.h", "")))

# ===========================================================================
print("")
print("[5] T5 privacy")
# ===========================================================================
_name = _pub0.attribution_name()


def private_literals(text: str) -> list:
    hits = []
    if _pub0.PRIVATE_AREA_PREFIX in text:
        hits.append("private area prefix")
    if _pub0.OCTOPUS_ID.search(text):
        hits.append("Octopus id")
    if re.search(r"\b" + re.escape(_name) + r"\b", text):
        hits.append("personal attribution name")
    return hits


_hunk_texts = [s for e in POST for fn in e.frozen_reverts.values() for pair in fn.edits for s in pair] + [s for p in X0.GATE_EDITS for s in p]
_added_texts = {f: X.read(f) for e in POST for f in e.added_files}
check("no post-export hunk and no gate hunk spells a private literal (private prefix, Octopus id, personal name)",
      not [h for t in _hunk_texts for h in private_literals(t)])
check("no file a post-export entry adds spells a private literal", not {f: private_literals(t) for f, t in _added_texts.items() if private_literals(t)},
      str({f: private_literals(t) for f, t in _added_texts.items() if private_literals(t)}))
check("the privacy detector is live (negative control: it flags each literal kind)",
      private_literals("x" + _pub0.PRIVATE_AREA_PREFIX) and private_literals(f"octopus_energy_electricity_12a3456789_{'1' * 13}_")
      and private_literals(f"SmartDeye/{_name}-listed"))

# ===========================================================================
print("")
print("[6] T6 immutability of the historical evidence")
# ===========================================================================
_deny_bad = [rel for rel, h in X.DENY_SHA.items() if X.sha(X.read(rel)) != h]
check("every deny-listed file (the pub0 module, its manifest, the 15 scope modules of 883068d) is byte-identical to 883068d", not _deny_bad, str(_deny_bad))
check("the pinned pub0 module hash is its manifest result, and the manifest still carries PUB0_FINGERPRINT",
      X.DENY_SHA[_pub0.SELF_REL] == RECS[_pub0.SELF_REL]["result_sha256"] and _pub0.manifest()["fingerprint"] == sc.PUB0_FINGERPRINT
      == "921c3ffefb5b233ffc7fd4d579f1c710fa1278fde03f9567eff9bf61269f45d6")
check("the closed pre-export chain (ROOT_COMMIT, ROOT_SHA, every field of the twelve ENTRIES and of PUB0, PUB0_FINGERPRINT) hashes to its "
      "883068d record", X.historical_chain_sha() == X.HISTORICAL_CHAIN_SHA == "d61b7b6a231006b2913ce62733f07df562056cffd6b633b5d8035ec06217dd4e",
      X.historical_chain_sha())
check("no post-export entry declares an edit to deny-listed historical data",
      not [f for e in POST for f in (*e.frozen_reverts, *e.reverts, *e.added_files) if f in X.DENY])
check("MANDATORY GATE PIN: registry/tests/test_pub0_transition.py is byte for byte its post-pex0 state (sha256)",
      X.sha(_gate) == PUB0_GATE_SHA256 == X0.GATE_SHA, X.sha(_gate))
check("...and it differs from its 883068d state by exactly pex0's four declared routings (undone exactly, it hashes to the 883068d gate)",
      X.sha(X0.pre_pex0_gate(_gate)) == PUB0_GATE_BASE_SHA256 == X0.GATE_BASE_SHA and X0.apply(X0.pre_pex0_gate(_gate), X0.GATE_EDITS, "gate") == _gate)

# ===========================================================================
print("")
print("[7] T7 the fingerprint chain")
# ===========================================================================
check("pex0's fingerprint is pinned here and links to pub0's manifest fingerprint (the genesis)",
      E0.fingerprint == PEX0_FINGERPRINT and X.record(E0)["parent"] == sc.PUB0_FINGERPRINT)
check("every post-export entry's recorded parent is the recorded fingerprint of the entry before it",
      all(X.record(e)["parent"] == (POST[i - 1].fingerprint if i else sc.PUB0_FINGERPRINT) for i, e in enumerate(POST)))

# ===========================================================================
print("")
print("[8] T8 the PEX ledger")
# ===========================================================================
LEDGER = {   # file -> exact number of calls of each _pex function
    "registry/tests/test_pub0_transition.py": {"as_of_pub0": 2},
    "registry/tests/test_fallback_recovery_dashboard.py": {"as_of_pub0": 2},
    "home-assistant/tests/test_ecco_fallback_packages.py": {"as_of_pub0": 4},
    "home-assistant/tests/test_ecco_shadow_check_ux.py": {"as_of_pub0": 2, "post_export_added": 1},
}
OWN_PEX = {"registry/tests/_pex.py", "registry/tests/_pex0_scope.py", "registry/tests/test_pex_transition.py"}
CALL = re.compile(r"\b_pex\.(\w+)\(")


def ledger_of(texts: dict) -> tuple[dict, list]:
    """{file: {function: calls}} of every file that imports or calls _pex, and the call lines with no `PEX` comment on the line or within
    the two lines above."""
    calls, uncommented = {}, []
    for rel, t in sorted(texts.items()):
        if rel in OWN_PEX or rel == "registry/tests/_scope_chain.py":
            continue
        lines = t.split("\n")
        if not (CALL.search(t) or re.search(r"(?m)^\s*import _pex\b(?!0)", t)):
            continue
        calls[rel] = dict(Counter(m.group(1) for m in CALL.finditer(t)))
        for i, line in enumerate(lines):
            if CALL.search(line) and not any("PEX" in lines[j] for j in range(max(0, i - 2), i + 1)):
                uncommented.append((rel, i + 1))
    return calls, uncommented


_py = [f for f in subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=str(ROOT), capture_output=True).stdout.decode("utf-8").split("\0") if f]
_py_texts = {f: (ROOT / f).read_text(encoding="utf-8", errors="replace") for f in _py}
_calls, _unc = ledger_of(_py_texts)
check("exactly the declared older-suite reads call _pex (the PUB0 gate and the three routed suites), with exactly the declared counts",
      len(_py) > 50 and _calls == LEDGER, str(_calls))
check("every _pex call carries a `PEX` comment on its line or within the two lines above", not _unc, str(_unc))
check("the chain module documents the layer but never imports it (no cycle; _pex reads the chain)",
      not re.search(r"(?m)^\s*(import _pex\b(?!0)|from _pex import)", _py_texts["registry/tests/_scope_chain.py"]))

# ===========================================================================
print("")
print("[9] T9 the whole chain on the live tree")
# ===========================================================================
_irows = sc.integrity_report(sc.CHAIN)
check(f"_scope_chain.integrity_report over root -> ENTRIES -> pub0 -> post-export is all green ({len(_irows)} rows)", all_ok(_irows), str(failing(_irows)[:3]))

# ===========================================================================
print("")
print("[10] adversarial mutations (each must be refused)")
# ===========================================================================


def report_broken(chain, live) -> bool:
    return not all_ok(X.report(chain, live))


def pairs_reverter(rel: str, edits: tuple):
    def revert_(text: str) -> str:
        return X0.revert(text, edits, f"synthetic {rel}")
    revert_.edits = edits
    return revert_


C = sc.CHAIN
# The synthetic entries below are anchored AS OF pex0 (the newest entry this suite knows) on the chain truncated there - like
# test_scope_chain's dump_v2 anchor - so a later real post-export entry never collides with them.
C_P0 = sc.Chain(C.upto("pex0"))
try:
    LIVE_P0 = {rel: X.as_of(rel, "pex0", LIVE[rel]) for rel in LIVE}
    _anchor_ok = True
except AssertionError:
    LIVE_P0, _anchor_ok = dict(LIVE), False
check("the synthetic scenarios' anchor: every frozen and chain-pinned file as of pex0 (the later entries undone exactly)", _anchor_ok)
check("M1: an undeclared edit to a frozen product file (the dashboard) is refused by the report and by as_of_pub0",
      report_broken(C, {**LIVE, DASH: LIVE[DASH] + "# undeclared\n"}) and raises(lambda: X.as_of_pub0(DASH, LIVE[DASH] + "# undeclared\n")))
check("M2: an undeclared edit to the enrolled VERSION.yaml is refused", report_broken(C, {**LIVE, VERSION: LIVE[VERSION] + "# x\n"})
      and raises(lambda: X.as_of_pub0(VERSION, LIVE[VERSION] + "# x\n")))
_SUITE = "home-assistant/tests/test_ecco_fallback_packages.py"
check("M3: an undeclared edit to a routed suite beyond pex0's hunks is refused", report_broken(C, {**LIVE, _SUITE: LIVE[_SUITE] + "# x\n"})
      and raises(lambda: X.as_of_pub0(_SUITE, LIVE[_SUITE] + "# x\n")))
check("M4: an undeclared edit to a chain-pinned artifact (the manifest) is refused by the report and by as_of_pub0",
      report_broken(C, {**LIVE, MANIFEST: LIVE[MANIFEST] + "# x\n"}) and raises(lambda: X.as_of_pub0(MANIFEST, LIVE[MANIFEST] + "# x\n")))


def with_pex0(**kw):
    return sc.Chain(PRE + (replace(E0, **kw),) + POST[1:])


check("M5: a wrong pex0 frozen checkpoint is refused", report_broken(with_pex0(frozen_checkpoints={**E0.frozen_checkpoints, _SUITE: "0" * 64}), LIVE))
_ident = (lambda t: t)
_ident.edits = E0.frozen_reverts[_SUITE].edits
check("M6: an identity frozen reverter (even one that claims pex0's pairs) is refused",
      report_broken(with_pex0(frozen_reverts={**E0.frozen_reverts, _SUITE: _ident}), LIVE))
_opaque = {**E0.frozen_reverts, _SUITE: (lambda f: (lambda t: f(t)))(E0.frozen_reverts[_SUITE])}
check("M7: a frozen reverter that does not expose its exact pairs (.edits) is refused", report_broken(with_pex0(frozen_reverts=_opaque), LIVE))
check("M8: a wrong pex0 fingerprint is refused", report_broken(with_pex0(fingerprint="f" * 64), LIVE))
check("M9: frozen edits or a fingerprint on an entry before pub0 are refused (ENTRIES are closed to PEX)",
      raises(lambda: sc.Chain(sc.ENTRIES + (replace(E0, id="early"),) + sc.EXPORT_ENTRIES), sc.ChainError)
      and raises(lambda: sc.Chain(sc.ENTRIES[:1] + (replace(sc.ENTRIES[1], fingerprint=PEX0_FINGERPRINT),) + sc.ENTRIES[2:]), sc.ChainError))
check("M10: a post-export entry without a 64-hex fingerprint is refused", raises(lambda: sc.Chain(PRE + (replace(E0, fingerprint=""),)), sc.ChainError))
check("M11: a frozen edit declared on a chain-pinned path, or a reverter without its checkpoint, is refused",
      raises(lambda: sc.Chain(PRE + (replace(E0, frozen_reverts={MANIFEST: lambda t: t}, frozen_checkpoints={MANIFEST: "0" * 64}),)), sc.ChainError)
      and raises(lambda: sc.Chain(PRE + (replace(E0, frozen_checkpoints={}),)), sc.ChainError))
_deny_entry = X.sealed(PRE + POST, sc.Entry(id="syn_deny", pr="SYN", commit="synthetic",
                                            frozen_reverts={_pub0.SELF_REL: pairs_reverter(_pub0.SELF_REL, (("EXPORTED = True", "EXPORTED = True "),))},
                                            frozen_checkpoints={_pub0.SELF_REL: X.sha(LIVE[_pub0.SELF_REL].replace("EXPORTED = True", "EXPORTED = True ", 1))}))
_deny_live = {**LIVE, _pub0.SELF_REL: LIVE[_pub0.SELF_REL].replace("EXPORTED = True", "EXPORTED = True ", 1)}
check("M12: a post-export entry declaring an edit to deny-listed historical data (the pub0 module itself) is refused, even when exact",
      any(not ok and "deny-listed" in n for n, ok, _d in X.report(sc.Chain(PRE + POST + (_deny_entry,)), _deny_live)))
_readme = sc.Entry(id="syn_readme", pr="SYN", commit="synthetic", fingerprint="0" * 64,   # cannot be sealed: README.md has no pub0 state
                   frozen_reverts={"README.md": pairs_reverter("README.md", (("a", "b"),))}, frozen_checkpoints={"README.md": "0" * 64})
check("M13: a frozen edit to a file that is not frozen (README.md) is refused (frozen means: a pub0 target or enrolled)",
      raises(lambda: X.report(sc.Chain(PRE + POST + (_readme,)), LIVE)) or report_broken(sc.Chain(PRE + POST + (_readme,)), LIVE))
P0 = C_P0.entries
_e1 = ("  - title: Manual Controls\n", "  - title: Manual  Controls\n")
_e1_live = {**LIVE_P0, DASH: LIVE_P0[DASH].replace(_e1[0], _e1[1], 1)}
_s1 = X.sealed(P0, sc.Entry(id="syn1", pr="SYN1", commit="synthetic", frozen_reverts={DASH: pairs_reverter(DASH, (_e1,))},
                            frozen_checkpoints={DASH: X.sha(_e1_live[DASH])}))
_e1x = ("# ECCO Pro Dashboard v7.16.0 - ", "# ECCO Pro Dashboard v7.16.0 (synthetic) - ")
_e1x_live = {**_e1_live, DASH: _e1_live[DASH].replace(_e1x[0], _e1x[1], 1)}
_s2 = X.sealed(P0 + (_s1,), sc.Entry(id="syn2", pr="SYN2", commit="synthetic", frozen_reverts={DASH: pairs_reverter(DASH, (_e1x,))},
                                     frozen_checkpoints={DASH: X.sha(_e1x_live[DASH])}))
check("M14 (control): two sealed synthetic entries editing the dashboard in turn pass every PEX row", all_ok(X.report(sc.Chain(P0 + (_s1, _s2)), _e1x_live)),
      str(failing(X.report(sc.Chain(P0 + (_s1, _s2)), _e1x_live))[:2]))
_s1_rewritten = X.sealed(P0, replace(_s1, note="rewritten", frozen_checkpoints={DASH: X.sha(_e1_live[DASH])}, pr="SYN1-REWRITTEN"))
check("M15: rewriting an OLDER post-export entry (re-sealed on its own) breaks the NEXT entry's fingerprint link",
      any(not ok and "syn2: its fingerprint" in n for n, ok, _d in X.report(sc.Chain(P0 + (_s1_rewritten, _s2)), _e1x_live)))
check("M16: two post-export entries applied in the wrong order are refused",
      raises(lambda: X.report(sc.Chain(P0 + (_s2, _s1)), _e1x_live)) or report_broken(sc.Chain(P0 + (_s2, _s1)), _e1x_live))
_hist = X.historical_record()
_hist["entries"][0]["note"] += " "
check("M17: any change to an old chain entry (one character of fba's note) changes the closed-history hash",
      X.sha(X._canonical(_hist)) != X.HISTORICAL_CHAIN_SHA)
check("M18: one changed byte in the PUB0 gate breaks its mandatory pin, and its routings no longer undo to the 883068d gate",
      X.sha(_gate.replace("PEX0", "PEX1", 1)) != PUB0_GATE_SHA256
      and (raises(lambda: X0.pre_pex0_gate(_gate.replace("restated", "re-stated", 1)))
           or X.sha(X0.pre_pex0_gate(_gate.replace("restated", "re-stated", 1))) != PUB0_GATE_BASE_SHA256))
_c, _u = ledger_of({"home-assistant/tests/x.py": "import _pex\ny = _pex.as_of_pub0('a', b)\n", **{k: _py_texts[k] for k in LEDGER}})
check("M19: the ledger refuses an undeclared, uncommented _pex call", _c != LEDGER and ("home-assistant/tests/x.py", 2) in _u)
_saved = _pub0.EXPORTED
try:
    _pub0.EXPORTED = False
    _private_identity = X.as_of_pub0(DASH, "any text") == "any text" and X.post_export(sc.Chain(sc.ENTRIES)) == ()
finally:
    _pub0.EXPORTED = _saved
check("M20: in a private tree (EXPORTED False) as_of_pub0 is the identity and a chain without pub0 has no post-export entry",
      _private_identity and raises(lambda: X.as_of(DASH, "pub0", LIVE[DASH], sc.Chain(sc.ENTRIES))))

# ===========================================================================
print("")
print("[11] synthetic E1-E3: undeclared they are refused; declared as one post-export entry they pass")
# ===========================================================================
# Anchored as of pex0 like M14-M16: the scenario is the same whatever real entries follow pex0.
_lines = LIVE_P0[TELEMETRY].split("\n")
_e2 = (_lines[0] + "\n" + _lines[1] + "\n", _lines[0] + "\n# house demand v2\n" + _lines[1] + "\n")
_e3 = ("\ndashboard:\n", "  - source: home-assistant/packages/ecco_house_demand.yaml\n"
                         "    destination: /config/packages/ecco_house_demand.yaml\n"
                         "    method: ssh_file_copy\n"
                         "    restart_required: true\n\ndashboard:\n")
check("the three synthetic edits apply to exactly one place each (E1 dashboard title, E2 telemetry top, E3 manifest package list)",
      LIVE_P0[DASH].count(_e1[0]) == 1 and LIVE_P0[TELEMETRY].count(_e2[0]) == 1 and LIVE_P0[MANIFEST].count(_e3[0]) == 1)
E_LIVE = {**LIVE_P0, DASH: LIVE_P0[DASH].replace(_e1[0], _e1[1], 1), TELEMETRY: LIVE_P0[TELEMETRY].replace(_e2[0], _e2[1], 1),
          MANIFEST: LIVE_P0[MANIFEST].replace(_e3[0], _e3[1], 1)}
SYN = X.sealed(P0, sc.Entry(
    id="syn_e123", pr="SYN-E123", commit="synthetic",
    reverts={MANIFEST: sc.exact_reverter([_e3], "syn_e123 manifest")}, checkpoints={MANIFEST: X.sha(E_LIVE[MANIFEST])},
    frozen_reverts={DASH: pairs_reverter(DASH, (_e1,)), TELEMETRY: pairs_reverter(TELEMETRY, (_e2,))},
    frozen_checkpoints={DASH: X.sha(E_LIVE[DASH]), TELEMETRY: X.sha(E_LIVE[TELEMETRY])},
    added_files=frozenset({"home-assistant/packages/ecco_house_demand.yaml"})))
CS = sc.Chain(P0 + (SYN,))
_pinned_E = {p: E_LIVE[p] for p in sc.PINNED}
for _label, _rel in (("E1 (dashboard wording)", DASH), ("E2 (telemetry package line)", TELEMETRY), ("E3 (manifest stanza)", MANIFEST)):
    _one = {**LIVE_P0, _rel: E_LIVE[_rel]}
    check(f"UNDECLARED {_label}: the PEX report and as_of_pub0 refuse it",
          report_broken(C_P0, _one) and raises(lambda r=_rel: X.as_of_pub0(r, E_LIVE[r], C_P0)))
check("UNDECLARED E3: the chain's integrity report refuses it too", not all_ok(sc.integrity_report(C_P0, _pinned_E)))
check("PARTLY DECLARED (the entry declares E1 and E2 only): E3 is still refused",
      report_broken(sc.Chain(P0 + (X.sealed(P0, replace(SYN, reverts={}, checkpoints={})),)), E_LIVE))
_rows_E = X.report(CS, E_LIVE)
check(f"DECLARED E1-E3: every PEX row passes ({len(_rows_E)} rows)", all_ok(_rows_E), str(failing(_rows_E)[:3]))
_irows_E = sc.integrity_report(CS, _pinned_E)
check(f"DECLARED E1-E3: the whole chain's integrity report passes ({len(_irows_E)} rows; E3 declares no counted delta)", all_ok(_irows_E),
      str(failing(_irows_E)[:3]))
_P0E = {rel: pub0_of(rel, E_LIVE[rel], CS) for rel in E_LIVE}
_bad_E = [rel for rel in _pub0.TARGETS if _P0E[rel] is None or X.sha(_P0E[rel]) != RECS[rel]["result_sha256"]]
check("DECLARED E1-E3: as of pub0 every one of the 57 pub0 targets is the pub0 export byte for byte (manifest result_sha256)", not _bad_E, str(_bad_E[:5]))
_dpriv = _pub0.private_view(DASH, _P0E[DASH]) if _P0E[DASH] is not None else ""
check("DECLARED E1-E3: the routed dashboard pins hold - as of pub0, private view, FB-C3 undone, it is the FB-B3 dashboard; FB-B3 undone, main @ 87e6151",
      bool(_dpriv) and c3.sha(_dpriv) == c3.DASHBOARD_AFTER_SHA and c3.sha(c3.pre_fbc3_dashboard(_dpriv)) == c3.DASHBOARD_BASE_SHA
      and ha3.sha(ha3.pre_fbb3_dashboard(c3.pre_fbc3_dashboard(_dpriv))) == ha3.DASHBOARD_BASE_SHA)
_man0 = yaml.safe_load(_P0E[MANIFEST] or "{}") or {}
check("DECLARED E1-E3: the routed manifest pins hold - as of pub0: 11 packages and release 2026-10-02-fbb3-dashboard; live: one package more",
      len(_man0.get("home_assistant_packages", [])) == 11 and _man0.get("release") == "2026-10-02-fbb3-dashboard"
      and len(yaml.safe_load(E_LIVE[MANIFEST])["home_assistant_packages"]) == len(yaml.safe_load(LIVE_P0[MANIFEST])["home_assistant_packages"]) + 1)
check("DECLARED E1-E3: the chain as of pex0 (and as of fbb3) sees the manifest without E3, byte for byte",
      CS.as_of(MANIFEST, "pex0", E_LIVE[MANIFEST]) == LIVE_P0[MANIFEST]
      and X.sha(CS.as_of(MANIFEST, "fbb3", E_LIVE[MANIFEST])) == CS.checkpoint(MANIFEST, "fbb3"))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All PEX (post-export edit layer) checks passed.")
print("These prove that every change made on the export is declared, exact, ordered and hash-linked, and that the pub0 export stays "
      "provable byte for byte; they prove nothing about hardware.")
