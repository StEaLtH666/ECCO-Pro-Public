"""acs1 (Advanced Configuration Stage 1: the guarded TOU settings editor replaces the Stage 0 target-SOC editor) change scope: what acs1
changes and what it deliberately does not, plus the files it adds.

WHAT acs1 IS. The Home Assistant package home-assistant/packages/ecco_tou_target_soc_edit.yaml (the acs0 editor of ONE TOU slot's target
SOC) is replaced, at the SAME path, by its Stage 1 successor: the same guarded flow (Review writes nothing -> a typed confirmation with a
one-time review code -> Apply, with a fresh configuration read, the Manual Controls helper sync at a fixed point, only the edited field
staged, every other staged value proven equal to the live slot, one Apply press in a quiet gap of the dongle's Modbus poll cycle, success
only on the firmware's VERIFIED OK plus two independent later reads, an uncertain outcome locks further edits until acknowledged) for ONE
setting of ONE slot: target SOC (as before), power, start time or charge source (None / Grid). The package drives the EXISTING, verified
manual TOU firmware path (Load Current Slot N To Manual Staging -> Manual Configuration Write Enable -> Apply Manual Slot N Settings);
that path already writes and verifies, for the slot, register 232 bit 0, the start / end pair, power, SOC and flags. ZERO firmware byte,
ZERO new register or write path (registry/tests/test_write_surface_invariants.py is unchanged), ZERO manifest change (same package path,
same stanza).

PENDING OWNER RE-APPROVAL. The reserved-token amendment of 2026-10-12 (Option A, see _acs0_scope.py) was approved for a SOC-only editor.
acs1 widens what the declared package does (power, start time, charge source) while the package reads EXACTLY the same six reserved ids
in the same three declared files, byte for byte (the gate lines that carry them are inherited untouched; the Stage 1 suite proves it).
acs1 declares no new reserved-token holder and amends no frozen allowlist; whether that suffices is the owner's decision.

THE DECISION ON REVERTERS (study: _scope_chain.Chain, _pex.report, _pex.FROZEN). An entry declares an edit to an existing file only for
  * a CHAIN-PINNED artifact (`Entry.reverts` / `checkpoints`; _scope_chain.PINNED: the firmware, its two headers, the capability registry,
    the state machine, the deployment manifest), or
  * a FROZEN file (`Entry.frozen_reverts` / `frozen_checkpoints`; _pex.FROZEN: the pub0 export targets that are not chain-pinned, plus
    the enrolled files), whose pub0-era state older suites pin, so that those suites can read it AS OF pub0.
The package is NEITHER: acs0 ADDED it after the pub0 export (it is an acs0 `added_files` entry, which is not hashed), no older suite pins
a pre-acs0 state of it, the chain refuses a reverter for an unpinned artifact (Chain.__init__) and _pex.report refuses a frozen edit to a
non-frozen file. Public PRs #31 and #32 edited it later without a chain entry for exactly that reason. acs1 therefore declares NO
reverter and NO checkpoint, and edits NO chain-pinned or frozen file: the deployment manifest, the four reserved-token suites and every
frozen allowlist are unchanged. The EXACT record of the package edit is held elsewhere and is proven offline:
  * home-assistant/prototypes/acs-stage1/acs_stage1_transform.py: 58 exact (before, after, count) pairs (40 reviewed + 18 follow-up); render_stage1(<Stage 0 text>) is
    the installed package byte for byte and unrender_stage1(<installed>) is the Stage 0 text again (sha256 ACS0_PACKAGE_SHA256);
  * home-assistant/tests/test_ecco_tou_slot_settings_edit.py: the installed file is tested directly, and [0] proves both directions, the
    pinned hashes (kept here as well, checked equal by [13]) and that the rollback file (the unrendered text) equals the old bytes.
What acs1 DOES declare: the files it adds (not hashed) and its fingerprint, which links it to hd1's and, through the chain, to pub0's.

ADDED FILES: the Stage 1 suite, the transform module (the provenance record), this module, the integration document and the candidate
document (the reuse proof, the per-setting matrix and the residual risks). The Stage 0 suite (test_ecco_tou_target_soc_edit.py) is an acs0
file, one of the three declared holders, and keeps its name and path: it now proves the Stage 0 baseline by running unchanged on
unrender_stage1(<installed>); the installed editor's behaviour is proven by the Stage 1 suite.

MERGE ORDER. acs1 is sealed to its parent hd1 (the fingerprint hashes hd1's). If another post-export entry merges first, acs1 must be
re-sealed on top of it: recompute the fingerprint with the sealed() helper of _pex (the chain up to the new parent, then ACS1), then update, together, the fingerprint
literal in _scope_chain.py, ACS1_FINGERPRINT and HD1_FINGERPRINT (the parent's) and the entry-position check in
home-assistant/tests/test_ecco_tou_slot_settings_edit.py, and the position of ACS1 in POST_EXPORT_ENTRIES.

FUTURE EDITS OF THE PACKAGE. The record is exact only while the package is render_stage1() of the Stage 0 text. A later edit of
home-assistant/packages/ecco_tou_target_soc_edit.yaml must APPEND pairs to the transform (and update its three pins - the transform's
STAGE1_SHA256 / PAIRS_SHA256, the Stage 1 suite's S1_SHA / PAIRS_SHA, and this module's STAGE1_PACKAGE_SHA256 / PAIRS_SHA256) or deliberately
retire the mechanism (a new chain entry that says so). An unpinned edit fails the Stage 1 suite.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

# Public main the change is based on (the signed candidate's base: fw-s0 equivalence checker, #37).
BASE_COMMIT = "e7a265b8d8779b7c15a47a6716f61d6a2227bc6f"

PACKAGE_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"

ADDED_FILES = frozenset({
    "docs/dev/acs-stage1-integration.md",
    "docs/dev/acs-stage1-local-candidate.md",
    "home-assistant/prototypes/acs-stage1/acs_stage1_transform.py",
    "home-assistant/tests/test_ecco_tou_slot_settings_edit.py",
    "registry/tests/_acs1_scope.py",
})

# sha256 (LF text) of the package before acs1 (acs0 + acs0r1 + the PR #31 / #32 edits, public main e7a265b8) and after it. The Stage 1
# suite proves that unrender_stage1(<installed>) and the installed text hash to these, and that they equal the transform module's pin.
ACS0_PACKAGE_SHA256 = "9fa32b9bb843cfc7b42bae9ed7c06a50f461e564d7f0609e2536c28968d6affe"
STAGE1_PACKAGE_SHA256 = "4cafc1926055fa71533d8a409ca520078b1c661e177c370649b2ce254e254816"
# sha256 of the canonical serialisation of the transform's 58 (before, after, count) pairs (acs_stage1_transform.pairs_sha256()).
PAIRS_SHA256 = "13ffda0da6c709d4a4192b0f2f1c2e2914371e2491ef4c6a31d0fcdf098b4f17"

# The script ids acs1 renames (nothing but documents refers to them; the helpers, the acknowledge script and the watchdog automation keep
# their ids) and the settings the new Review takes.
SCRIPT_RENAMES = (
    ("ecco_cfg_review_tou_slot_soc", "ecco_cfg_review_tou_slot_setting"),
    ("ecco_cfg_apply_tou_slot_soc", "ecco_cfg_apply_tou_slot_setting"),
)
SETTINGS = ("target_soc", "power", "start_time", "charge_source")
