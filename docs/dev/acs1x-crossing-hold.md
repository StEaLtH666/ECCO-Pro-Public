# Advanced Configuration Stage 1, midnight-crossing hold (post-export entry `acs1x`)

Status: **OFFLINE SOURCE CHANGE. CORRECTED FOR THE FINDINGS OF AN INDEPENDENT REVIEW (2026-10-27); THE CORRECTED CHANGE AWAITS ITS OWN
INDEPENDENT RE-CHECK. NOT INSTALLED. NO REGISTER WRITTEN. NO FIRMWARE CHANGE.** Local work on branch `dev/acs1-crossing-hold` from public
main `e97ba36c` (the acs1c merge, PR #45). Nothing in this change touches Home Assistant, the dongle, the inverter or InfluxDB. It only adds a
refusal to the guarded TOU editor's scripts (and rewrites four refusal texts so that each fits its result helper whole); it never writes
anything and never widens what the editor accepts.

## 1. Why

acs1c ([acs1c-cyclic-tou.md](acs1c-cyclic-tou.md)) replaced the editor's "strictly ascending" start-time rule with a cyclic one, so every
slot of the owner's layout (starts 00:30, 05:30, 12:00, 16:35, 22:00, 00:25 by slot number; slot 5 runs 22:00 -> 00:25 past midnight)
became start-time editable through the Review / Apply scripts. A single valid edit can then also move the **midnight crossing**, the
slot that runs into the next day, to another slot: slot 6 00:25 -> 23:55 makes slot 6 run past midnight, slot 5 22:00 -> 00:05 makes slot
4 do so. The firmware and the dongle treat the six slots as a ring, but the inverter's own scheduler has only been observed with the
crossing where the owner has it (slot 5 into slot 6); `APPLIED AND VERIFIED` proves the registers, not which slot the inverter runs at a
given minute (acs1c section 8).

The owner approved acs1c for source integration only, with a restriction: the midnight crossing is not moved to a different slot in
normal operation until a separately authorised, supervised hardware test proves the behaviour. As installed, nothing in the scripts would
have enforced it: a direct script call could still apply a crossing-moving layout. On 2026-10-27 the owner directed a fail-closed,
**script-level** restriction that does not rely on the dashboard or on operating instructions, kept until the supervised relocated-crossing
verification has been separately authorised and completed, with the existing TOU layout preserved and start-time editing still disabled in
the dashboard. acs1x is that restriction. No relocated-crossing test is authorised by it or needed for it.

## 2. The rule (`xw`)

**Definition.** Read the six live starts as minutes of the day, `tt[0..5]` (slot 1..6; -1 when a start does not read as HH:MM). A slot
pair `k -> k+1` (indices modulo 6) is a *raw decrease* when `tt[(k + 1) % 6] < tt[k]`: the next slot's start is earlier in HH:MM than
this slot's, so slot `k + 1` runs into the next day (or ends exactly at midnight). The gate counts the raw decreases of the LIVE layout
and of the PROPOSED layout (the same list with slot `n`'s start replaced by the new value, built exactly as acs1c's proposed-layout test
builds it) and requires **exactly one in each, at the same index**; otherwise the start-time edit is refused with a plain-language text
(156 characters):

> the new start time would change which slot runs past midnight (the midnight crossing): not allowed until a supervised test on the
> inverter has been approved

It is false (refuse) on anything unreadable: a live start that is not HH:MM, an unreadable new start, or a slot outside 1-6.

**Why exactly one.** Each of acs1c's forward gaps `(tt[k+1] - tt[k]) mod 1440` equals the raw difference, plus 1440 exactly when the raw
difference is negative. The six raw differences of a cycle sum to 0, so the six gaps sum to 1440 x (the number of raw decreases). acs1c's
`cyc` demands that sum be 1440, so a layout that passes `cyc` has exactly one raw decrease: the crossing, which always runs from the latest
start to the earliest. The proposed layout passes `cyc2`, so the same holds for it. The two count requirements are therefore defence in
depth after `cyc` / `cyc2`; the index comparison is the rule.

**Equivalent readings** (both checked as independent oracles by the suite): the slot that owns the last minute of the day (the slot with
the latest start) is the same before and after the edit; and the moved boundary does not pass 00:00 (counted from the previous slot's
start, 00:00 does not lie after the lower and at or before the higher of the old and the new start). A start at exactly 00:00 is after
midnight (owner's decision, 2026-10-27): slot 6 at 00:00 keeps the crossing between slots 5 and 6 (slot 5 then ends at midnight) and is
allowed; slot 5 at 00:00 moves it to slot 4 -> 5 and is refused.

**On the owner's layout** (crossing slot 5 -> 6):

| Slot | Window acs1c allows | Refused by the hold | Still allowed |
|---|---|---|---|
| 1 | 00:35 .. 05:25 | none | all |
| 2 | 00:35 .. 11:55 | none | all |
| 3 | 05:35 .. 16:30 | none | all |
| 4 | 12:05 .. 21:55 | none | all |
| 5 | 16:40 .. 00:20 (past midnight) | 00:00 .. 00:20 (5 values) | 16:40 .. 23:55 |
| 6 | 22:05 .. 00:20 (before midnight) | 22:05 .. 23:55 (23 values) | 00:00 .. 00:20 |

(the 15-minute and active-slot guards still apply to everything allowed). Slots 1-4 never reach midnight on this layout, so the hold never
fires for them.

**The crossing is held wherever the live layout has it.** The rule does not know where the crossing "should" be. On a layout whose
crossing was moved by another tool (Manual Controls drives the firmware path directly and is outside this package), the editor cannot
move it back either while the hold stands; that needs Manual Controls under the owner's supervision, or the hold lifted.

## 3. Where: all four copies of the gate, and none of them is redundant

The package evaluates the same gate four times: the Review; the Apply's gate (before anything else); its re-check after the fresh
configuration read; its last check before the press (indents 12 / 12 / 16 / 24). In each copy:

- the two lines that compute `xc` (the counts and indices) and `xw` sit right before acs1c's proposed-layout test (its `h` loop, then
  `cyc2`), whose list they build the same way;
- the refusal sits right after acs1c's proposed-layout refusal (`not cyc2`) and right before the 15-minute guard, so it is reported before
  the 15-minute and active-slot guards.

The later copies are **not** redundant. The edited slot's own live start is compared with the review record only by the Apply's gate and
at the fresh read; between the fresh read and the press the last copy is the only check that sees it change. If another tool moves slot
N's live start in that window (for example slot 6 from 00:25 to 23:00 while slot 6 -> 00:20 is being applied), the same reviewed edit
would move the crossing, and only the last copy refuses it. The fresh-read copy can likewise differ from the Apply's gate when the other
five starts move. The suite tests each copy rendered alone and, end to end, the cases where only the last copy refuses (section 6). A
Review record edited by hand to a crossing-moving value is refused by the Apply's own gate before any Load.

**The last check's result text.** A refusal by the last copy is written as `FAILED - a safety check changed just before the Apply (` +
refusal + `); nothing pressed, nothing written`, which adds 90 characters, into an `input_text` that holds 255. A longer value is not
stored, so the designed FAILED path (its notice and the F2 re-Load of slot N's staging, both keyed on that result) would not run, and a
refused start could stay staged in Manual Controls. Four refusals were longer than 165 characters (255 - 90): acs1c's cycle (177) and
neighbour (167) texts, acs1's power text (216; not reachable at the last check, whose typed value the Apply's gate has already passed) and
acs1's fallback live match text (158 plus its value of up to 16; reachable when the live match changes after the fresh read); the first
version of this layer's own text (187) was too (independent review, finding X1). acs1x **rewrites** the four, shorter and with the same
meaning, in all four copies, and its own text is 156 characters; **nothing is truncated**:

| Refusal | Before | After |
|---|---|---|
| cycle (acs1c) | 177 | 163: "the six live slot start times are not one 24-hour cycle in slot order (5-minute grid, every slot at least 5 minutes, one wrap past midnight): unexpected TOU layout" |
| neighbour (acs1c) | 167 | 157: "the new start time must lie strictly after the previous slot's start and before the next slot's start, counted round the clock (slot 6 is followed by slot 1)" |
| power (acs1) | 216 | 162: "power must be a multiple of 100 W, 500 to 8000 W (below 500 W the slot leaves the saved fallback profile's domain and later edits, the undo included, are refused)" |
| fallback live match (acs1) | 158 + 16 | 145 + 16: "the fallback live match is <value>: edits need a valid saved fallback profile, live settings in its domain and export as saved (MATCH, DRIFT or CONTEXT)" |

The suite bounds every value written to the three `input_text` helpers (17 writers) at its longest: each substitution at a stated maximum
with its reason (a slot, a label, a 16-bit register, a sensor state, a slice), each refusal variable at the longest refusal of its own copy,
an unlisted expression failing the check. It runs five last-copy-only cases end to end (the hold for slot 6 and slot 5, the cycle, the
neighbour and the fallback live match refusals): each records the FAILED result, sends the notice, re-Loads the edited slot (staging equal
to the live slot) and presses and writes nothing.

## 4. What does not change

Target SOC, power and charge-source edits (same result text and notification as before). Every acs1c rule (`cyc`, `order`, `cyc2`, the
unwrapped active-slot guard, the form re-check of the typed value), every other guard, the fresh evidence, the staged == live proof, the
quiet-window single press, the firmware readback, the two later reads, the gate-pass counter, F1 / F2, the UNCERTAIN lock. Four refusal
texts read shorter (section 3); what they refuse is unchanged. No firmware byte, register, write path, service call, entity or helper; no manifest stanza; no dashboard or card
file (the TOU Settings card keeps start times display-only; enabling start-time editing in the dashboard is a later, separate change). The
owner's TOU layout is not touched by anything here.

## 5. Provenance: a third invertible layer

As acs1c did on acs1, acs1x adds `home-assistant/prototypes/acs-stage1/acs1x_transform.py`: 12 exact `(before, after, count)` pairs applied
to the acs1c text (`render_crossing`), invertible (`unrender_crossing`): two for the header (the generation note and the description of
the rule), per indent (12 x2, 16, 24) one for the `xc` / `xw` lines and one for the refusal, and one per rewritten refusal text (four
copies each).

| Pin | Value | Meaning |
|---|---|---|
| `STAGE1C_BASE_SHA256` | `4ee898311a6abe7a7b0bc1874bff2cd10027d14f4122b341f5145833e3d90405` | the acs1c text the pairs apply to = acs1c's `STAGE1C_SHA256` (public main `e97ba36c`) |
| `STAGE1X_SHA256` | `850f10fda78071220521ab04d2ca46c43bbbed2649090502a0e9e82a02b71262` | `render_crossing(<acs1c text>)`, the package on this branch |
| `CROSSING_PAIRS_SHA256` | `13e6b93c7336f786cad82bb0ba0fd1dd60c6dae02423299f26e185b5a4b5b719` | the canonical serialisation of the 12 pairs |

The package is `render_crossing(render_cyclic(render_stage1(<Stage 0 text>)))`; each earlier text derives from the installed file alone.
**`unrender_crossing` gives the acs1c text as provenance, not as an installable rollback:** installed alone, the acs1c text accepts and
applies crossing-moving edits. While the restriction stands, an installed rollback goes to the previous site render (the Stage 1 package
installed on 2026-10-25) or to any render that keeps the hold, never to the acs1c text alone. Every pair anchors on whole lines next to the
change, none on, spelling or rewriting a line that carries a reserved fallback / failback token (the 20 such gate lines and the six
reserved ids are inherited untouched). The anchors are chosen so that no direction can be confused: `render_crossing` refuses an
already-rendered text, `unrender_crossing` refuses an acs1c text, and `unrender_cyclic` refuses the installed text (the `xc` / `xw` lines
sit inside acs1c's block of ordering lines).

Chain: a new post-export entry `acs1x` after `acs1c` (`registry/tests/_scope_chain.py`, scope module `registry/tests/_acs1x_scope.py`),
declaring only the files it adds and its fingerprint (`775ddcd0...`, sealed with `_pex.sealed` on acs1c's `9b4e5b34...`; the
fingerprint binds the declaration, the suite's pins bind the package bytes); no reverter, no checkpoint, no reserved-token holder, no
frozen or chain-pinned file. The PEX ledger counts the Stage 1 suite's four extra `_pex` calls. Edited, not hashed: the Stage 1 suite, the
Stage 0 suite's loading lines (it runs, otherwise unchanged, on the Stage 0 text recovered through all three layers), a note in
[acs1c-cyclic-tou.md](acs1c-cyclic-tou.md), a section of [post-export-edit-layer.md](post-export-edit-layer.md) and the CHANGELOG.

## 6. Tests (offline, all local)

`home-assistant/tests/test_ecco_tou_slot_settings_edit.py` (the Stage 1 suite; run from the repository root):

- `[0]` / `[0x]` provenance of all three layers, both ways, pins asserted; every acs1x pair removed, duplicated or altered is refused
  naming the pair; the untouched-line proof with mutants; the check and its refusal once in each of the four copies at its place; every
  value written to the three result helpers within 255 characters at its longest (shown not to hold on the acs1c text); the four rewritten
  texts in all four copies, keeping their meaning; the hold's text in plain words, distinct from every other refusal class;
- `[4]` / `[4c]` the acs1c tables, with the crossing-moving cases now expecting the hold (slot 5 past midnight, slot 6 before it, slot 1 at
  23:55 on a layout whose slot 1 starts at 00:00); the active-slot guard across midnight is exercised on the acs1c text, and the installed
  package refuses each of those cases with the hold;
- `[4x]` every single-slot start edit of the owner's layout (6 slots x 288 grid values) through each of the four copies rendered alone,
  against the reference model (`acs1x_transform.verdict` after `acs1c_transform.verdict`); 240 real Reviews (slots 5 and 6 at every grid
  value 21:00 .. 00:55, every slot at each full hour); the owner's named cases against the acs1c text (which accepts them all); hand-edited
  review records refused by the Apply's own gate before any Load; the hold alone failing closed, with one case per conjunct (`xc.ok`,
  `tt[k] >= 0`, `xc.c == 1`, `xc.c2 == 1`) that only that conjunct refuses, through all four copies; the crossing held where the live layout
  has it; target SOC, power and charge-source Reviews identical to the acs1c text's; 30 random cyclic layouts through all four copies;
  20,000 model cases (the gap identity, one crossing from the latest start, two independent oracles, only the two slots around the crossing
  can move it, rotation invariance);
- `[11x]` the last copy refusing alone, end to end (a live start or the fallback live match changes after the Load): the hold for slot 6
  and its mirror for slot 5, acs1c's cycle and neighbour refusals, the fallback live match refusal; each records the FAILED result within
  255 characters, sends the notice, re-Loads the edited slot (staging == live) and presses and writes nothing; on the acs1c text the slot 6
  race is pressed and written; on the package as first committed (the long texts, a 187-character hold text; rebuilt in memory) each
  case fails as the review reproduced it (no result, no notice, no F2 re-Load, the value left staged);
- `[12]` mutants, each KILLED by a failing behavioural check: the hold dropped from all four copies, from the Review only, from the Apply's
  gate only, from the fresh-read re-check only and from the last check only (caught by rendering each copy alone, and the last one also end
  to end), each of the four conjuncts dropped, the index comparison dropped, the proposed layout built without the new start, the hold moved
  after the 15-minute and active-slot guards, a rewritten refusal restored to its long form in the last check (cycle, neighbour, fallback
  live match). Two acs1c mutants (two wraps allowed; the
  active-slot guard linear again) are now refused by the hold first, so their checks run with the hold turned off in memory;
- `[13]` the acs1x declaration: position, hash link to acs1c, added files, no frozen or chain-pinned edit, pins equal across the suite,
  the transform and the scope module.

Also: the Stage 0 suite, `registry/tests/test_scope_chain.py`, `test_pex_transition.py`, the four reserved-token suites,
`test_write_surface_invariants.py`, `tools/validate_repo.py`, the TOU card suite and `tools/run_offline_tests.py`. Results are recorded in
the project's review records, outside this repository.

What the suites do NOT prove: anything about a live Home Assistant, the dongle or the inverter; the inverter scheduler's behaviour with a
relocated crossing (the reason for the hold); how a real Home Assistant version handles an over-long `input_text` value (the simulator keeps
the old value; the rewrites make the case unreachable for every value the helper is given).

## 7. Residuals and limits

- The hold is a policy restriction, not a safety proof: it keeps the editor inside the one crossing position evidenced on the inverter.
  Lifting the restriction needs the supervised relocated-crossing proof (acs1c section 7, step 4) and a separately reviewed change that
  removes or relaxes this layer.
- Manual Controls (the firmware's manual TOU path, driven directly) is outside this package and unchanged; the restriction stays an
  operating rule there.
- A layout whose crossing was moved elsewhere by another tool cannot be moved back through the editor (section 2).
- On every input the shipped gate can reach, the two count requirements and the readability flag are implied by acs1c's `cyc` / `cyc2`,
  which come first in all four copies; the suite pins each of them with its own case once those rules are turned off in memory (section 6).

## 8. Next steps (each needs the owner's separate authorisation; none is started)

1. Independent re-check of the corrected commit in a separate reviewer window.
2. Push of `dev/acs1-crossing-hold`, its own PR, full CI, the private-pattern privacy run, merge.
3. Installation: acs1c and acs1x are installed together (public main then carries both); the acs1c install path (kit, gates, a fresh
   backup, install without restart or inverter write, read-only acceptance, the supervised start-time proof that never moves the crossing)
   applies unchanged, with the hold's refusals added to the read-only acceptance (for example a slot 6 Review to 23:55 refused, nothing
   written); its rollback is the previous site render, never the acs1c text alone.
