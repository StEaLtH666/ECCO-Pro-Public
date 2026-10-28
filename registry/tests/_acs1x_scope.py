"""acs1x (Advanced Configuration Stage 1, midnight-crossing hold: a start-time edit that would move the midnight crossing to another slot
boundary is refused by the scripts themselves) change scope: what acs1x changes and what it deliberately does not, plus the files it adds.

WHAT acs1x IS. acs1c (public main e97ba36c, PR #45) made the start-time ordering rule of the guarded TOU editor
home-assistant/packages/ecco_tou_target_soc_edit.yaml cyclic: every slot of the owner's layout (starts 00:30, 05:30, 12:00, 16:35, 22:00,
00:25 by slot number; slot 5 runs past midnight into slot 6) became start-time editable through the Review / Apply scripts, and a single
edit could then also move the midnight crossing to another slot (slot 6 00:25 -> 23:55, or slot 5 22:00 -> 00:05). The inverter's
scheduler has only been observed with the owner's crossing position. The owner approved acs1c for source integration only, with the
restriction that the midnight crossing is not moved to a different slot in normal operation until a separately authorised, supervised
hardware test proves the behaviour; and on 2026-10-27 directed that the restriction be enforced by a fail-closed, script-level check, not
only by the dashboard or by operating instructions. acs1x adds that restriction to the four copies of the gate: in a layout that is one 24-hour
cycle in slot order exactly one slot pair has a next start earlier in raw HH:MM minutes than its own (the crossing); the gate counts those
raw decreases in the live layout and in the proposed one (built exactly as acs1c's proposed-layout test builds it) and requires exactly
one in each, at the same index, else it refuses ("the new start time would change which slot runs past midnight ..."); anything
unreadable refuses. It also rewrites four refusal texts (acs1c's cycle and neighbour texts, acs1's power and fallback live match texts),
shorter and never truncated, so that every value written to the 255-character result helper fits at its longest and the designed FAILED path
of the last check (its notice, the F2 re-Load) runs; those four did not fit that check's 90-character frame (review finding, 2026-10-27). Target SOC, power and charge-source edits are unaffected; every other guard, proof, press, readback and lock is byte
for byte acs1c's. ZERO firmware byte, ZERO new register, write path, service call or entity, ZERO manifest change (same package path, same
stanza). The dashboard card keeps start times display-only (unchanged).

WHY A THIRD LAYER. As acs1c did on acs1, acs1x keeps the acs1 and acs1c transforms, their pins and their declarations byte for byte and adds
a third invertible transform on top of the acs1c text (home-assistant/prototypes/acs-stage1/acs1x_transform.py: 12 exact (before, after,
count) pairs; render_crossing(<the acs1c text>) is the installed package and unrender_crossing(<installed>) is the acs1c text again). The
acs1c text (sha256 STAGE1C_PACKAGE_SHA256, public main e97ba36c) is recoverable from the installed file alone, as provenance: it is NOT an
installed rollback while the restriction stands (installed alone it accepts crossing-moving edits); an installed rollback goes to the
previous site render (the Stage 1 package of 2026-10-25) or to any render that keeps the hold. The Stage 1 text and the Stage 0 text are
recoverable through the other two layers. The Stage 1 suite proves all three layers, both ways.

THE DECISION ON REVERTERS is acs1's and acs1c's: the package is neither chain-pinned nor frozen, so acs1x declares NO reverter and NO
checkpoint and edits NO chain-pinned or frozen file; the package reads exactly the same six reserved ids in the same three declared files
(no acs1x pair anchors on, spells or rewrites a line that carries one); acs1x declares no new reserved-token holder.

WHAT acs1x DOES declare: the files it adds (not hashed) and its fingerprint, which links it to acs1c's and, through the chain, to pub0's.

ADDED FILES: the acs1x transform module (the provenance record), this module and the design document. EDITED (not hashed): the Stage 1
suite (provenance of the third layer, the crossing cases, the per-copy checks and mutants, its [13] checks of this declaration), the Stage 0
suite's loading lines (it now runs on the Stage 0 text recovered through all three layers), the acs1c design document (a note),
docs/dev/post-export-edit-layer.md (a section), CHANGELOG.md (an entry) and the PEX ledger of registry/tests/test_pex_transition.py (the
Stage 1 suite's four extra _pex calls: one fingerprint, one record, two checkpoint). EDITED (chain): registry/tests/_scope_chain.py (this
entry appended).

OWNER STATUS. Offline implementation at the owner's direction of 2026-10-27 (backend enforcement of the crossing restriction), corrected
for the findings of an independent review (2026-10-27); the corrected change awaits its own independent re-check. NOT installed, NOT
live-proven. No relocated-crossing test is authorised. Push, PR, merge and any install each need the owner's separate approval. Lifting
the restriction means a supervised relocated-crossing proof AND a separately reviewed change that removes this layer.

MERGE ORDER. acs1x is sealed to acs1c (public main e97ba36c). If another post-export entry merges first, acs1x must be re-sealed on top of
it: recompute the fingerprint with the sealed() helper of _pex (the chain up to the new parent, then ACS1X), then update, together, the
fingerprint literal in _scope_chain.py, FINGERPRINT here, ACS1X_FINGERPRINT in the Stage 1 suite and the position of ACS1X in
POST_EXPORT_ENTRIES.

FUTURE EDITS OF THE PACKAGE. The record is exact only while the package is render_crossing(render_cyclic(render_stage1(<Stage 0 text>))).
A later edit must APPEND pairs to the acs1x transform (and update its pins STAGE1X_SHA256 / CROSSING_PAIRS_SHA256, the Stage 1 suite's
S1X_SHA / XPAIRS_SHA and this module's STAGE1X_PACKAGE_SHA256 / CROSSING_PAIRS_SHA256 / CROSSING_PAIR_COUNT) or declare a further layer
with its own chain entry. An unpinned edit fails the Stage 1 suite.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

# Public main the change is based on: the acs1c merge (PR #45).
BASE_COMMIT = "e97ba36cdc19796d0d1b136b6da27c0212dd6bef"

PACKAGE_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"

ADDED_FILES = frozenset({
    "docs/dev/acs1x-crossing-hold.md",
    "home-assistant/prototypes/acs-stage1/acs1x_transform.py",
    "registry/tests/_acs1x_scope.py",
})

# sha256 (LF text) of the package before acs1x (the acs1c text: acs1c's STAGE1C_SHA256, public main e97ba36c; provenance, not an installed rollback)
# and after it (the installed package). The Stage 1 suite proves that unrender_crossing(<installed>) and the installed text hash to these, and
# that they equal the acs1x transform's pins.
STAGE1C_PACKAGE_SHA256 = "4ee898311a6abe7a7b0bc1874bff2cd10027d14f4122b341f5145833e3d90405"
STAGE1X_PACKAGE_SHA256 = "850f10fda78071220521ab04d2ca46c43bbbed2649090502a0e9e82a02b71262"
# sha256 of the canonical serialisation of the acs1x transform's 12 (before, after, count) pairs (acs1x_transform.crossing_pairs_sha256()).
CROSSING_PAIRS_SHA256 = "13e6b93c7336f786cad82bb0ba0fd1dd60c6dae02423299f26e185b5a4b5b719"
CROSSING_PAIR_COUNT = 12

# The fingerprint of this entry (the literal in _scope_chain.py; checked equal by the Stage 1 suite).
FINGERPRINT = "775ddcd098a21f4971c594abf383af696fe40785654197b5916bd62c1ce2014f"

# The rule, as data (the Stage 1 suite reads the gate's own text; these name the policy for the record).
RULES = (
    "xw: in the live layout and in the proposed one (slot n's start replaced by the new value) exactly one slot pair has a next start earlier "
    "in raw HH:MM minutes than its own (the midnight crossing), at the same index in both; otherwise the start-time edit is refused",
    "fail closed: an unreadable live start, an unreadable new start or a slot outside 1-6 makes xw false",
    "placement: right after acs1c's proposed-layout refusal (cyc2) in all four copies of the gate, before the 15-minute and active-slot guards",
    "result helper: four refusal texts are rewritten, shorter and never truncated, so every value written to the 255-character result helper "
    "fits at its longest (the last check's frame adds 90 characters, so each refusal stays within 165)",
    "kept: every acs1c rule (cyc, order, cyc2, mid), every other guard, the staged == live proof, one press, the readback, F1 / F2, the lock; "
    "target SOC, power and charge-source edits unaffected",
)
