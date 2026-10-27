"""acs1c (Advanced Configuration Stage 1, cyclic TOU correction: the start-time ordering rule becomes one 24-hour cycle in slot order)
change scope: what acs1c changes and what it deliberately does not, plus the files it adds.

WHAT acs1c IS. The Home Assistant package home-assistant/packages/ecco_tou_target_soc_edit.yaml (the acs1 editor of ONE setting of ONE TOU
slot) refused every start-time Review of the owner's live layout (starts 00:30, 05:30, 12:00, 16:35, 22:00, 00:25 by slot number) with
"the six live slot start times are not strictly ascending (unexpected TOU layout)": its gate demanded tt[0] < tt[1] < ... < tt[5] on the
HH:MM values and set naive neighbour bounds (-1 below slot 1, 24:00 above slot 6). The inverter's six slots are a ring (slot N runs from its
start to slot N+1's start, slot 6 into slot 1 the next day; the fallback capture's ring_valid and the Dump to Grid conflict check already
treat them so), and that layout is a valid 24-hour schedule (gaps 300, 390, 275, 325, 145 and 5 minutes; slot 5 runs past midnight). acs1c
replaces the ordering rule, in the four copies of the gate, by a cyclic one: the live layout must be one valid cycle in slot order (every
start HH:MM on the 5-minute grid, every slot at least 5 minutes, the six forward gaps modulo 24 h adding up to exactly 1440 minutes: one
wrap past midnight, no overlap, no gap); the new start must lie strictly between the previous and the next slot's start, counted round
the clock from the previous slot's start (slot 6 precedes slot 1); the proposed layout must itself be one cycle (defence in depth, proven
equivalent); and the active-slot-now guard is evaluated in the same unwrapped minutes, so a window that crosses midnight is judged
correctly. Every other guard, the staged == live proof, the quiet-window single press, the readback, F1 / F2 and the UNCERTAIN lock are
byte for byte as acs1 left them. The value staged and written is still the typed HH:MM on the grid (00:00-23:55); unwrapped minutes exist
only in comparisons. ZERO firmware byte, ZERO new register or write path (the firmware's per-slot Apply gate has no ordering assumption:
valid_hhmm on start and end, start != end), ZERO manifest change (same package path, same stanza).

WHY A SECOND LAYER, NOT MORE acs1 PAIRS. acs1's record (_acs1_scope.py) allows a later package edit to append pairs to the acs1 transform
and move its three pins, or to declare a new chain entry. acs1c keeps the acs1 transform, its pins and its declaration byte for byte and
adds a second invertible transform on top of the Stage 1 text (home-assistant/prototypes/acs-stage1/acs1c_transform.py: 21 exact (before,
after, count) pairs; render_cyclic(<the Stage 1 text>) is the installed package and unrender_cyclic(<installed>) is the Stage 1 text again).
That keeps the exact record of the package installed on 2026-10-25 (sha256 STAGE1_PACKAGE_SHA256, the site render 1c724e76 of which is
live): it is the rollback file of this correction, recoverable from the installed file alone, and the Stage 0 text is still recoverable
through both layers (unrender_stage1(unrender_cyclic(<installed>))). The Stage 1 suite proves both layers, both ways.

THE DECISION ON REVERTERS is acs1's: the package is neither chain-pinned nor frozen (an acs0 `added_files` entry), so acs1c declares NO
reverter and NO checkpoint and edits NO chain-pinned or frozen file: the deployment manifest, the four reserved-token suites and every
frozen allowlist are unchanged; the package reads EXACTLY the same six reserved ids in the same three declared files (the gate lines that
carry them are inherited untouched: no acs1c pair anchors on, spells or rewrites one). acs1c declares no new reserved-token holder.

WHAT acs1c DOES declare: the files it adds (not hashed) and its fingerprint, which links it to acs1's and, through the chain, to pub0's.

ADDED FILES: the acs1c transform module (the provenance record), this module and the design document. EDITED (not hashed): the Stage 1
suite (its provenance checks cover both layers; its start-time cases cover the cyclic rule; its mutation battery kills the cyclic
mutants; its [13] checks this declaration), the two acs1 design documents (a note each), docs/dev/post-export-edit-layer.md (a section),
CHANGELOG.md (an entry), the PEX ledger of registry/tests/test_pex_transition.py (the Stage 1 suite's four extra _pex calls: one
fingerprint, one record, two checkpoint) and the Stage 0 suite's loading and provenance lines (the import, the load and the assert; it
now runs, otherwise unchanged, on unrender_stage1(unrender_cyclic(<installed>))). EDITED (chain): registry/tests/_scope_chain.py (this
entry appended). The package file at the install path is called "the installed package" below once this correction is installed; until
then it is the candidate and the live install is the Stage 1 site render of 2026-10-25.

OWNER STATUS. Offline implementation at the owner's direction of 2026-10-25 (Window C). Independently reviewed on 2026-10-25 (logic, tests and
provenance accepted; documentation corrections applied), NOT installed, NOT live-proven: a start-time edit has never been applied on the
real inverter through this path. The owner's approved policy P3 (2026-10-21, "start times strictly ascending") is superseded by this
cyclic rule only when the owner approves it after the independent review (policy P3c, proposed). Installation, the supervised live proof
(one inactive start time moved by 5 minutes and back) and the dashboard start-time control each need their own owner authorisation.

MERGE ORDER. acs1c was first sealed to acs1; the dashboard entry acu1 merged first (public main 07b37c14, 2026-10-26), so acs1c was
rebased onto it and re-sealed as acu1's child (the fingerprint hashes acu1's). If another post-export entry merges first again, acs1c must be
re-sealed on top of it: recompute the fingerprint with the sealed() helper of _pex (the chain up to the new parent, then ACS1C), then
update, together, the fingerprint literal in _scope_chain.py, FINGERPRINT here, ACS1C_FINGERPRINT in the Stage 1 suite and the position of
ACS1C in POST_EXPORT_ENTRIES.

FUTURE EDITS OF THE PACKAGE. The record is exact only while the package is render_cyclic(render_stage1(<Stage 0 text>)). A later edit must
APPEND pairs to the acs1c transform (and update its pins STAGE1C_SHA256 / CYCLIC_PAIRS_SHA256, the Stage 1 suite's S1C_SHA / CPAIRS_SHA and
this module's STAGE1C_PACKAGE_SHA256 / CYCLIC_PAIRS_SHA256 / CYCLIC_PAIR_COUNT) or declare a further layer with its own chain entry, as
acs1c did. An unpinned edit fails the Stage 1 suite.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

# Public main the change is based on: the acs1 merge (PR #41), the source of the package installed on 2026-10-25.
BASE_COMMIT = "a7235433ce711e6a8fae5dab0fc8ca6c6f533de6"

PACKAGE_REL = "home-assistant/packages/ecco_tou_target_soc_edit.yaml"

ADDED_FILES = frozenset({
    "docs/dev/acs1c-cyclic-tou.md",
    "home-assistant/prototypes/acs-stage1/acs1c_transform.py",
    "registry/tests/_acs1c_scope.py",
})

# sha256 (LF text) of the package before acs1c (the Stage 1 text: acs1's STAGE1_SHA256, installed 2026-10-25 and the rollback file of this
# correction) and after it (the installed package). The Stage 1 suite proves that unrender_cyclic(<installed>) and the installed text hash to
# these, and that they equal the acs1c transform's pins.
STAGE1_PACKAGE_SHA256 = "2e8813973d133b7bd25fe273af16403af4cea0b8e64b338a015f35412346e9de"
STAGE1C_PACKAGE_SHA256 = "4ee898311a6abe7a7b0bc1874bff2cd10027d14f4122b341f5145833e3d90405"
# sha256 of the canonical serialisation of the acs1c transform's 21 (before, after, count) pairs (acs1c_transform.cyclic_pairs_sha256()).
CYCLIC_PAIRS_SHA256 = "6cb46976e90d4c7a7e24206d562ee532e4b4246c3595100e10de514075f4d761"
CYCLIC_PAIR_COUNT = 21

# The fingerprint of this entry (the literal in _scope_chain.py; checked equal by the Stage 1 suite).
FINGERPRINT = "9b4e5b349ef18de9c9ddf36bd61e98d85ac8da5443ce3240377cd370797aaffc"

# The rule, as data (the Stage 1 suite reads the gate's own text; these name the policy for the record).
GRID_MINUTES = 5
DAY_MINUTES = 1440
MIN_SLOT_MINUTES = 5
RULES = (
    "cyc: the six live starts are one 24-hour cycle in slot order (each HH:MM on the 5-minute grid, every slot at least 5 minutes, the six "
    "forward gaps modulo 24 h adding up to exactly 1440 minutes: one wrap past midnight)",
    "order: the new start lies strictly between the previous and the next slot's start, counted round the clock from the previous slot's "
    "start (slot 6 precedes slot 1)",
    "cyc2: the proposed layout (the live one with the edited start replaced) is itself one 24-hour cycle (defence in depth, equivalent to cyc "
    "and order for a one-slot change)",
    "mid: the active-slot-now guard compares the local time with the old and the new boundary in the same unwrapped minutes",
    "kept: the 15-minute distance from the old and the new boundary, the 5-minute grid and 00:00-23:55 bound of the typed value, the "
    "inverter-clock rule, the clock-change-night refusal, every other gate, the staged == live proof, one press, the readback, F1 / F2, the lock",
)
