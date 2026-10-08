"""PEX - the POST-EXPORT EDIT LAYER (schema ecco-pex/1; foundation entry pex0, registry/tests/_pex0_scope.py).

WHY. The public tree IS the pub0 export (registry/tests/_pub0_scope.py, EXPORTED = True). pub0 froze its 57 targets at their result
sha256 (registry/tests/fixtures/pub0_manifest.json): test_pub0_transition.py requires each of them to be exactly the export, and the
older suites' historical pins read several of them through pub0's positional reverse(). An ordinary edit to any of them - a Home
Assistant package, the dashboard, an older suite - therefore fails the pub0 proof; the manifest cannot be regenerated in the export (the
generator refuses an exported tree, and the tariff identifiers are not in it), and re-hashing is forbidden (_scope_chain.py). PEX lets
such a change land WITHOUT touching that evidence: every change made on the export is ONE declared, exact, ordered, hash-linked chain
entry AFTER pub0 (_scope_chain.POST_EXPORT_ENTRIES), and the proofs read the files AS OF pub0.

WHAT IS FROZEN. FROZEN = the pub0 targets that are not chain-pinned, plus ENROLLED: files pub0 did not edit whose pub0-era state an older
suite pins (owner decision O3: VERSION.yaml; O3 amendment, esb1: the Energy Actions card's package.json, package-lock.json and
bundle, whose pub0-era state the FB-B3 / FB-C3 folder pins and the lic0 suite pin; never broadened without such evidence). The pub0
state of a frozen file (the PEX genesis) is base(): the manifest's result sha256 for a target (read from the manifest, never typed)
and the recorded hash for an enrolled file. The chain-pinned artifacts keep their own mechanism (Entry.reverts / checkpoints); their
pub0 state is the chain checkpoint as of pub0.

THE CONTRACT (proven by test_pex_transition.py):
  as_of(rel, entry_id, live)  the live file with every post-export entry newer than entry_id undone, newest first. Fails closed: rel must
                              be frozen or chain-pinned, the live text must be exactly the newest declared state (sha256), and every step
                              must land exactly on the declared state before that entry. as_of_pub0(rel, live) is as_of(rel, "pub0",
                              live); it is the identity in the private tree (PEX is public-tree-only, owner decision O5).
  fingerprint(entry, chain)   sha256 of the entry's canonical record: schema, id, PR, its PARENT's fingerprint (PUB0_FINGERPRINT for the
                              first post-export entry) and, for every file it edits, the sha256 before and after it, plus every other
                              declaration. An older entry cannot be rewritten without changing every later fingerprint.
  report(chain, live)         (name, ok, detail) rows over every post-export entry, like _scope_chain.integrity_report.
  DENY / DENY_SHA             historical proof data no post-export entry may edit, byte-identical to public main @ BASE_COMMIT.
  HISTORICAL_CHAIN_SHA        the canonical record of the root, the twelve ENTRIES and PUB0 at BASE_COMMIT: the pre-export chain is closed.
A frozen reverter exposes its exact (before, after) pairs as `.edits` (the privacy and exactness proofs read them).

No I/O except reading repo files.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import _pub0_scope as _pub0
import _scope_chain as sc

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

SCHEMA = "ecco-pex/1"
EXPORT_ID = "pub0"
# Public main @ this commit is the pub0 export as published: the state every post-export entry starts from (the PEX genesis).
BASE_COMMIT = "883068daf63e51ff0e79c9f2cc427a3124f6cccb"

# O3: files pub0 did not edit whose pub0-era state a frozen suite pins. sha256 (LF text) at BASE_COMMIT (`git show <commit>:<path>`).
ENROLLED = {
    "VERSION.yaml": "4cbc651f9d7fcc7cc3af645360be5122cc102c7821bd2d9dc788962fef7d53e3",   # FB-B3 / FB-C3 version pins
    # O3 amendment (esb1, owner-approved 2026-10-08): the three Energy Actions card files the esbuild 0.28.1 upgrade changes. Three
    # frozen suites pin the card folder's pub0-era (FB-B3) state through lic0, and test_lic0_transition.py pins the lic0 bundle.
    "frontend/ecco-energy-actions-card/package.json": "494c8c96ef80338b4613caf4f40eed1aa2bedde0220f7f2446c1751a1b57181b",
    "frontend/ecco-energy-actions-card/package-lock.json": "aa389e0bb311846f87543eb0ca0023c87315faadad03bf5c8b7710f888a768fd",
    "frontend/ecco-energy-actions-card/dist/ecco-energy-actions-card.js":
        "c1bd37deb0dab7ad1933e5276e70388643b14b55ed57842f055eadfb1933c207",   # == _lic0_scope.DIST_POST_SHA256
}
FROZEN = (frozenset(_pub0.TARGETS) - frozenset(sc.PINNED)) | frozenset(ENROLLED)

# Historical proof data: the pub0 module and manifest, and every scope module that existed at BASE_COMMIT. No post-export entry may
# declare an edit to them, and each stays byte-identical to its BASE_COMMIT content (sha256, LF text).
DENY_SHA = {
    "registry/tests/_dump_v2_scope.py": "cb1a62d83b8b3be76943b4580c6f955c3cc039d5929ace8fb9c46a2ffd77277c",
    "registry/tests/_fba_scope.py": "72b65bc5847ad245cb11f8c0a5dbac24077b9198441271917e384778880fa267",
    "registry/tests/_fbb1_scope.py": "64df300722607d979b7a908398d2aa3b3ddd2555c94a1b658ca80d094b3aae42",
    "registry/tests/_fbb2_scope.py": "737c126311be4e9aac605c6e7e0efe40debf136d896fc84e4a8b9658f236b02a",
    "registry/tests/_fbb3_ha_scope.py": "00c8a990ffaca14103590f21a4ae9845f986b9fb66fcf981e50031f813153c4a",
    "registry/tests/_fbb3_scope.py": "50cb989826b7161eb24b7deb811eae5d52308fe16344eb271624c54b6089b5f1",
    "registry/tests/_fbb_scope.py": "64a3f12d4ad940fca85f4d5662b700d176024498720338613825749abab5c363",
    "registry/tests/_fbc2_scope.py": "1c9ac358b2ad06e0949af0954703f8886f05bda996d606b1695c5e3f15c577f2",
    "registry/tests/_fbc3_scope.py": "c8647706baacefc6e9f0a72be95db3b9a5b077c2a85ab15c16b52e89e8ba73cf",
    "registry/tests/_fbc_scope.py": "c851d7d03b200cf6dc4225cce6f15b33977d9afa8014570a608b69b8dffdc4a6",
    "registry/tests/_fbd1_scope.py": "225b3647ec5b90b7f7d6990a0ba1369cb4ea199f6280f27f42153969d3a51a76",
    "registry/tests/_lic0_scope.py": "749b788928e8604f6d25fc8eac960753f563bc773e3e54dc675c75d5934e4d36",
    "registry/tests/_mtou1_scope.py": "d77f87e93affafaf23f8c31b31a8e398d550ad8977f33a7cb0f8f1546a4685e9",
    "registry/tests/_pub0_scope.py": "fb7c71ca3b2dc0f5318939bc26b36d29e39d4795b8a8afc036624045c41b8135",
    "registry/tests/_sg06_scope.py": "483bde1097d12651ba100494a02227e7b0cef08574e1651e719d3b2a54bf79d9",
    "registry/tests/fixtures/pub0_manifest.json": "470eaf2202ad15491dfe24432344194285d8386a45b83e5f4e9ddd094b90123a",
}
DENY = frozenset(DENY_SHA)

# sha256 of historical_record() at BASE_COMMIT: ROOT_COMMIT, ROOT_SHA, every field of the twelve ENTRIES and of PUB0, PUB0_FINGERPRINT.
HISTORICAL_CHAIN_SHA = "d61b7b6a231006b2913ce62733f07df562056cffd6b633b5d8035ec06217dd4e"

_HEX64 = re.compile(r"[0-9a-f]{64}")


class PexError(AssertionError):
    """A post-export declaration does not match the files (a failed proof, never a skipped one)."""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read(rel: str) -> str:
    """A repo text file as the suites read it (Path.read_text: universal newlines -> LF)."""
    return (REPO / rel).read_text(encoding="utf-8")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------------------------------------------------------
# The pub0 state (genesis) and the declared states after it
# ---------------------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _pre_export_chain() -> "sc.Chain":
    return sc.Chain(sc.ENTRIES + sc.EXPORT_ENTRIES)


def base(rel: str) -> str:
    """sha256 of `rel` in the pub0 export: the manifest result (a pub0 target), the enrolled hash, or the chain checkpoint as of pub0."""
    if rel in sc.PINNED:
        return _pre_export_chain().checkpoint(rel, EXPORT_ID)
    if rel in ENROLLED:
        return ENROLLED[rel]
    recs = _pub0.records()
    if rel in recs:
        return recs[rel]["result_sha256"]
    raise PexError(f"PEX: {rel} is neither chain-pinned, a pub0 target nor enrolled: it has no pub0 state")


def post_export(chain: "sc.Chain | None" = None) -> tuple:
    """The post-export entries of `chain` (everything after pub0), in merge order; () when the chain carries no pub0."""
    c = chain or sc.CHAIN
    ids = c.ids()
    return tuple(c.entries[ids.index(EXPORT_ID) + 1:]) if EXPORT_ID in ids else ()


def post_export_added(chain: "sc.Chain | None" = None) -> frozenset:
    """Every file a post-export entry declares as added: the pub0 export did not have it (an undeclared new file is not in this set)."""
    return frozenset().union(frozenset(), *(e.added_files for e in post_export(chain)))


def checkpoint(rel: str, entry_id: str, chain: "sc.Chain | None" = None) -> str:
    """sha256 `rel` must have at `entry_id` (pub0 or later)."""
    c = chain or sc.CHAIN
    if rel in sc.PINNED:
        return c.checkpoint(rel, entry_id)
    return c.frozen_checkpoint(rel, entry_id, base(rel))


def _reverter(e, rel: str):
    return (e.reverts if rel in sc.PINNED else e.frozen_reverts).get(rel)


def as_of(rel: str, entry_id: str, text: str, chain: "sc.Chain | None" = None) -> str:
    """`text` (the LIVE `rel`) with every post-export entry newer than `entry_id` undone, newest first; see the module docstring."""
    c = chain or sc.CHAIN
    if rel not in FROZEN and rel not in sc.PINNED:
        raise PexError(f"PEX: {rel} is neither frozen (a pub0 target or enrolled) nor chain-pinned: as_of refuses it")
    if EXPORT_ID not in c.ids():
        raise PexError(f"PEX: the chain carries no {EXPORT_ID}: this is not the export (PEX is public-tree-only)")
    post = post_export(c)
    ids = [e.id for e in post]
    if entry_id != EXPORT_ID and entry_id not in ids:
        raise PexError(f"PEX: {entry_id!r} is neither {EXPORT_ID!r} nor a post-export entry ({ids})")
    newest = ids[-1] if ids else EXPORT_ID
    want = checkpoint(rel, newest, c)
    if sha(text) != want:
        raise PexError(f"PEX {rel}: not the newest declared state (sha256 {sha(text)[:16]} != {want[:16]}, as of {newest}): "
                       "an undeclared edit (declare it in a post-export entry)")
    for e in reversed(post):
        if e.id == entry_id:
            break
        fn = _reverter(e, rel)
        if fn is None:
            continue
        text = fn(text)
        prev = c.prev_id(e.id)
        want = checkpoint(rel, prev, c)
        if sha(text) != want:
            raise PexError(f"PEX {rel}: undoing {e.id} does not land on the declared state as of {prev} "
                           f"(sha256 {sha(text)[:16]} != {want[:16]})")
    return text


def as_of_pub0(rel: str, text: str, chain: "sc.Chain | None" = None) -> str:
    """`text` (the LIVE `rel`) exactly as the pub0 export spells it: every post-export edit undone (exact, sha256-checked at every step).
    The identity in the private tree, where the live files are pub0's source and there is no post-export layer."""
    if not _pub0.EXPORTED:
        return text
    return as_of(rel, EXPORT_ID, text, chain)


# ---------------------------------------------------------------------------------------------------------------------------
# Fingerprints (hash-linked, append-only)
# ---------------------------------------------------------------------------------------------------------------------------
def record(entry, chain: "sc.Chain | None" = None) -> dict:
    """The canonical record a post-export entry's fingerprint hashes. `commit` and `note` are metadata and are not hashed (recording the
    merge commit later never re-keys the chain)."""
    c = chain or sc.CHAIN
    post = post_export(c)
    ids = [e.id for e in post]
    if entry.id not in ids:
        raise PexError(f"PEX: {entry.id!r} is not a post-export entry of this chain ({ids})")
    i = ids.index(entry.id)
    prev = c.prev_id(entry.id)
    return {
        "schema": SCHEMA,
        "id": entry.id,
        "pr": entry.pr,
        "parent": post[i - 1].fingerprint if i else sc.PUB0_FINGERPRINT,
        "pinned": {p: [checkpoint(p, prev, c), entry.checkpoints[p]] for p in sorted(entry.reverts)},
        "frozen": {p: [checkpoint(p, prev, c), entry.frozen_checkpoints[p]] for p in sorted(entry.frozen_reverts)},
        "deltas": {k: entry.deltas[k] for k in sorted(entry.deltas)},
        "op_paths_changed": sorted(entry.op_paths_changed),
        "includes_added": list(entry.includes_added),
        "subst_added": {k: entry.subst_added[k] for k in sorted(entry.subst_added)},
        "subst_changed": {k: list(entry.subst_changed[k]) for k in sorted(entry.subst_changed)},
        "subst_removed": sorted(entry.subst_removed),
        "fbh_includers": sorted(entry.fbh_includers),
        "banned_fw_added": entry.banned_fw_added,
        "banned_files": sorted(entry.banned_files),
        "added_files": sorted(entry.added_files),
        "tags_declared": sorted(entry.tags_declared),
        "tags_promoted": sorted(entry.tags_promoted),
    }


def fingerprint(entry, chain: "sc.Chain | None" = None) -> str:
    return sha(_canonical(record(entry, chain)))


def sealed(prefix: tuple, entry):
    """`entry` with the fingerprint it has as the next entry after `prefix` (chain entries ending at pub0 or a post-export entry). For
    computing a new entry's fingerprint and for the proofs; the fingerprint the chain carries is a literal in _scope_chain.py."""
    draft = replace(entry, fingerprint="0" * 64)
    return replace(entry, fingerprint=fingerprint(draft, sc.Chain(tuple(prefix) + (draft,))))


# ---------------------------------------------------------------------------------------------------------------------------
# The closed pre-export history
# ---------------------------------------------------------------------------------------------------------------------------
def entry_declaration(e) -> dict:
    """Every field of a pre-export entry (its reverters by module-qualified name)."""
    return {
        "id": e.id, "pr": e.pr, "commit": e.commit,
        "reverts": {p: f"{fn.__module__}.{fn.__name__}" for p, fn in sorted(e.reverts.items())},
        "checkpoints": dict(sorted(e.checkpoints.items())),
        "deltas": dict(sorted(e.deltas.items())),
        "op_paths_changed": sorted(e.op_paths_changed),
        "includes_added": list(e.includes_added),
        "subst_added": dict(sorted(e.subst_added.items())),
        "subst_changed": {k: list(v) for k, v in sorted(e.subst_changed.items())},
        "subst_removed": sorted(e.subst_removed),
        "fbh_includers": sorted(e.fbh_includers),
        "banned_fw_added": e.banned_fw_added,
        "banned_files": sorted(e.banned_files),
        "added_files": sorted(e.added_files),
        "tags_declared": sorted(e.tags_declared),
        "tags_promoted": sorted(e.tags_promoted),
        "note": e.note,
    }


def historical_record() -> dict:
    """The root, the twelve merge-ordered ENTRIES and PUB0, as declared (pinned by HISTORICAL_CHAIN_SHA)."""
    return {"root_commit": sc.ROOT_COMMIT, "root_sha": dict(sorted(sc.ROOT_SHA.items())),
            "entries": [entry_declaration(e) for e in sc.ENTRIES],
            "export_entries": [entry_declaration(e) for e in sc.EXPORT_ENTRIES],
            "pub0_fingerprint": sc.PUB0_FINGERPRINT}


def historical_chain_sha() -> str:
    return sha(_canonical(historical_record()))


# ---------------------------------------------------------------------------------------------------------------------------
# The machine check
# ---------------------------------------------------------------------------------------------------------------------------
def exact_pairs(edits) -> bool:
    """True for a non-empty tuple of (before, after) string pairs, each a real change."""
    return (isinstance(edits, tuple) and bool(edits)
            and all(isinstance(p, tuple) and len(p) == 2 and all(isinstance(s, str) for s in p) and p[0] != p[1] for p in edits))


def report(chain: "sc.Chain | None" = None, live: Mapping[str, str] | None = None) -> list[tuple[str, bool, str]]:
    """Machine-check every post-export entry of `chain` against `live` (default: the repo). Returns (name, ok, detail) rows; every row
    must be ok. The chain-pinned rows of each entry (deltas, op paths, includes, substitutions) are _scope_chain.integrity_report's."""
    c = chain or sc.CHAIN
    rows: list[tuple[str, bool, str]] = []
    if EXPORT_ID not in c.ids():
        rows.append((f"the chain carries {EXPORT_ID} (PEX is public-tree-only)", False, str(c.ids()[-3:])))
        return rows
    post = post_export(c)
    files = sorted(FROZEN | set(sc.PINNED))
    cur = {rel: live[rel] if live is not None and rel in live else read(rel) for rel in files}
    newest = post[-1].id if post else EXPORT_ID
    bad = [rel for rel in files if sha(cur[rel]) != checkpoint(rel, newest, c)]
    rows.append((f"live: every frozen and chain-pinned file ({len(files)}) is exactly its newest declared state (as of {newest}): "
                 "no undeclared edit", not bad, str(bad[:5])))
    states = {newest: dict(cur)}
    for e in reversed(post):
        nxt = dict(cur)
        try:
            for rel, fn in (*e.reverts.items(), *e.frozen_reverts.items()):
                nxt[rel] = fn(cur[rel])
        except Exception as exc:  # noqa: BLE001 - a reverter that cannot apply is a FAILED proof, never a skipped one
            rows.append((f"{e.id}: its declared reverters apply exactly to the files as of {e.id}", False,
                         f"{type(exc).__name__}: {str(exc)[:200]}"))
            return rows
        states[c.prev_id(e.id)] = cur = nxt
    for i, e in enumerate(post):
        prev = c.prev_id(e.id)
        declared = {**e.checkpoints, **e.frozen_checkpoints}
        bad = [rel for rel in declared if sha(states[e.id][rel]) != declared[rel]]
        rows.append((f"{e.id}: every file it declares is exactly its recorded checkpoint", not bad, str(bad)))
        bad = [rel for rel in declared if sha(states[prev][rel]) != checkpoint(rel, prev, c)]
        rows.append((f"{e.id}: undoing it lands every file it declares exactly on the declared state as of {prev}", not bad, str(bad)))
        vac = [rel for rel in declared if states[prev][rel] == states[e.id][rel]]
        rows.append((f"{e.id}: every declared reverter changes its file (none is an identity)", not vac, str(vac)))
        bad = [rel for rel in files if sha(states[e.id][rel]) != checkpoint(rel, e.id, c)]
        rows.append((f"{e.id}: as of {e.id} every frozen and chain-pinned file is exactly its declared state", not bad, str(bad[:5])))
        outside = sorted(set(e.frozen_reverts) - FROZEN)
        rows.append((f"{e.id}: its frozen edits name only frozen files (pub0 targets that are not chain-pinned, or enrolled)",
                     not outside, str(outside)))
        denied = sorted((set(e.frozen_reverts) | set(e.reverts) | set(e.added_files)) & DENY)
        rows.append((f"{e.id}: it declares no edit to deny-listed historical proof data", not denied, str(denied)))
        opaque = sorted(rel for rel, fn in e.frozen_reverts.items() if not exact_pairs(getattr(fn, "edits", None)))
        rows.append((f"{e.id}: every frozen reverter exposes its exact (before, after) pairs as .edits", not opaque, str(opaque)))
        fp = fingerprint(e, c)
        rows.append((f"{e.id}: its fingerprint is the sha256 of its canonical record, linked to its parent "
                     f"({post[i - 1].id if i else EXPORT_ID})", bool(_HEX64.fullmatch(e.fingerprint)) and fp == e.fingerprint,
                     f"computed {fp} recorded {e.fingerprint}"))
    bad = [rel for rel in files if sha(states[EXPORT_ID][rel]) != base(rel)]
    rows.append(("as of pub0 every frozen file is its pub0 state (manifest result / enrolled hash) and every chain-pinned artifact its "
                 "pub0 checkpoint", not bad, str(bad[:5])))
    return rows
