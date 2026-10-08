"""fbrp1 (public fallback records / design basis) change scope: exactly what fbrp1 changes in a file the pub0 export froze, and its
exact inverse.

Same technique as the earlier post-export scope modules: the verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair, and the reverter raises unless the edit is present exactly once. The post-export chain entry `fbrp1`
(registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last; registry/tests/_pex.py) carries `pre_fbrp1_version` as its one
frozen reverter.

WHAT fbrp1 IS. A records and documentation change, nothing else. It publishes the fallback design basis and stage status
(docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md, added) and corrects public status text that still described the FB-C3 shadow
display as offline only. ZERO firmware, Home Assistant package, dashboard, frontend, deployment, registry, Intelligence or ecco_core
change; ZERO Modbus operation (64 reads / 52 writes unchanged); ZERO NVS access; ZERO behaviour change. So the chain entry has no
chain-pinned reverter, no checkpoint and no counted delta.

FROZEN edit (PEX). VERSION.yaml (enrolled by owner decision O3) changes in exactly one place: the comment of the 7.18.0 dashboard
block. The old text called FB-C3 "OFFLINE / STAGED / NOT LIVE-PROVEN"; the new text records it as deployed and partially live-proven
(the everyday display path checked live, the supervision-loss path not yet). `tested_in_home_assistant` stays `false`, byte for
byte: the flag records a dashboard release exercised in full, and the supervision-loss path has not been. pre_fbrp1_version undoes
the edit exactly, so as of pub0 VERSION.yaml is the export byte for byte (its enrolled hash) and the older suites' pub0-era
VERSION.yaml pins (routed through _pex.as_of_pub0 by pex0) still read the export text. The live checks on VERSION.yaml (no private
development history, pure line endings, no Review Age entity) keep reading the live file.

NOT frozen (ordinary edits, nothing to declare): README.md, SUPPORTED_HARDWARE.md, ARCHITECTURE.md and CHANGELOG.md.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (Intelligence V1.1, squash-merged as PR #7). No post-export entry before fbrp1 edits
# VERSION.yaml, so its text there is the enrolled pub0 state.
BASE_COMMIT = "f8789b3c185982b290cc582376b3a4dc9403293a"
VERSION_REL = "VERSION.yaml"
# sha256 (LF text, as Path.read_text returns it) of VERSION.yaml at BASE_COMMIT: what pre_fbrp1_version() must reproduce. It is
# the enrolled pub0 hash (_pex.ENROLLED).
VERSION_BASE_SHA = "4cbc651f9d7fcc7cc3af645360be5122cc102c7821bd2d9dc788962fef7d53e3"

ADDED_FILES = frozenset({
    "docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md",
    "registry/tests/_fbrp1_scope.py",
})


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- (PEX frozen edit) VERSION.yaml: the 7.18.0 dashboard status comment ---------------------------------------------------------
VERSION_STATUS_OLD = _blk(r"""
    # shadow_episode, FAILBACK_SHADOW_EPISODE, decoder sensor.ecco_shadow_check). FB-C3 is
    # OFFLINE / STAGED / NOT LIVE-PROVEN: offline Jinja and contract tests only, no firmware change.
    # tested_in_home_assistant is therefore false for 7.18.0. The previous dashboard release (7.17.0,
""")
VERSION_STATUS_NEW = _blk(r"""
    # shadow_episode, FAILBACK_SHADOW_EPISODE, decoder sensor.ecco_shadow_check), no firmware change. FB-C3 is
    # DEPLOYED on the reference installation (2026-10-04) and PARTIALLY LIVE-PROVEN: its everyday display path was
    # checked live (the readiness Verdict wording, the canonical Fallback status, the health rows and the Safety
    # view, all from the real dongle strings). Its supervision-loss path (the Shadow Recovery status, the
    # shadow-episode banner and the episode detail) has NOT been exercised in a live proof yet; that needs an
    # authorised Home Assistant loss drill. tested_in_home_assistant therefore stays false for 7.18.0: the flag
    # records a dashboard release exercised in full. Stage status:
    # docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md. The previous dashboard release (7.17.0,
""")
VERSION_EDITS = ((VERSION_STATUS_OLD, VERSION_STATUS_NEW),)


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"fbrp1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def pre_fbrp1_version(text: str) -> str:
    """VERSION.yaml with exactly fbrp1's one edit undone (the frozen reverter of chain entry fbrp1, PEX): the pub0 export's text.
    The edited block must occur exactly once, else AssertionError; after the revert the export block must again be unique."""
    out = text
    for before, after in reversed(VERSION_EDITS):
        out = _swap(out, after, before, "VERSION.yaml status edit", "present")
    for before, _after in VERSION_EDITS:
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"fbrp1 scope: the VERSION.yaml anchor must be unique once the edit is removed, found {n}x")
    return out


pre_fbrp1_version.edits = VERSION_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_fbrp1_version(text: str) -> str:
    """Applies fbrp1's VERSION.yaml edit to the exported text (the round trip). The exported block must occur exactly once."""
    out = text
    for before, after in VERSION_EDITS:
        if after in out:
            raise AssertionError("fbrp1 scope: the VERSION.yaml status edit is already present")
        out = _swap(out, before, after, "VERSION.yaml status anchor", "found")
    return out
