# Advanced Configuration Stage 1, cyclic TOU correction (post-export entry `acs1c`)

Status: **OFFLINE SOURCE CORRECTION, INDEPENDENTLY REVIEWED OFFLINE (2026-10-25/26). NOT INSTALLED. NOT LIVE-PROVEN. NO REGISTER
WRITTEN. NO FIRMWARE CHANGE.** Local work on branch `dev/acs1-cyclic-tou` from public main `a7235433` (the acs1 merge, PR #41, the source of the package
installed on 2026-10-25). Nothing in this change touches Home Assistant, the dongle, the inverter or InfluxDB. The owner directed this
correction on 2026-10-25: the limitation is to be resolved in the software, not hidden or worked around, and the owner's inverter
schedule is not to be changed to fit the validation. The owner's schedule is not changed by anything here.

## 1. The limitation (L1) and why it was a software limitation

The inverter's six TOU slots are a ring: slot N runs from its own start (register 249+N) to slot N+1's start, and slot 6 runs into slot 1
the next day (slot 6's end is register 250). The owner's live layout, by slot number, is

| Slot | Start | Runs | Minutes |
|---|---|---|---|
| 1 | 00:30 | 00:30 -> 05:30 | 300 |
| 2 | 05:30 | 05:30 -> 12:00 | 390 |
| 3 | 12:00 | 12:00 -> 16:35 | 275 |
| 4 | 16:35 | 16:35 -> 22:00 | 325 |
| 5 | 22:00 | 22:00 -> **00:25 next day** | 145 |
| 6 | 00:25 | 00:25 -> 00:30 next day | 5 |

The six intervals partition the day exactly once (1440 minutes), with one wrap past midnight inside slot 5. The firmware's own
cyclic predicate (`registry/fallback_capture.py` `ring_valid`, used by the fallback capture and shown as `ring=OK` in the B6/B8
context) accepts it; the firmware's per-slot Apply gate (`valid_hhmm` on start and end, `start != end`, no ordering assumption) accepted
the slot 5 power and charge-source writes of 25 Oct with the pair 22:00 / 00:25 staged. The Stage 1 editor alone refused every start-time
Review of this layout: its gate computed `asc = tt[0] < tt[1] < ... < tt[5]` on the HH:MM minutes (1320 < 25 is false) and bounded the
new start by `lb = tt[n-2]` (-1 for slot 1) and `hb = tt[n]` (1440 for slot 6), a line, not a ring. Its active-slot-now guard (`mid`)
compared the two HH:MM minutes on a line too, which for a window that crosses midnight would have tested the complement of the window.

## 2. What acs1c installs (the start_time setting only)

In each of the four copies of the gate (the Review; the Apply's gate; its re-check after the fresh configuration read; its last check
before the press), the ordering lines are replaced:

| Rule | Stage 1 (acs1) | acs1c |
|---|---|---|
| `cyc` (the live layout) | `asc`: strictly ascending HH:MM values, `tt[0] >= 0`, `tt[5] < 1440` | one 24-hour cycle in slot order: every start reads as HH:MM on the 5-minute grid, every slot lasts at least 5 minutes (the forward gap to the next slot's start, modulo 24 h, is >= 5), and the six gaps add up to exactly 1440 minutes (the slots go round the clock once: exactly one wrap, no overlap, no gap) |
| `order` (the new start) | `lb < wmin < hb` with `-1` and `1440` sentinels | `0 < (new - prev) mod 1440 < (next - prev) mod 1440`: strictly between the previous and the next slot's start, counted round the clock from the previous slot's start. Slot 6 precedes slot 1; slot 1 follows slot 6. The slot keeps its identity and neighbours; no slot can become zero or negative, change owner, overlap, leave a gap or cross another boundary |
| `cyc2` (the proposed layout) | - | the live layout with the edited start replaced is itself one 24-hour cycle. Equivalent to `cyc` and `order` for a one-slot change (proof below; also checked on 20,000 random cases); kept as an independent check of the whole proposed schedule |
| `mid` (active slot now) | `(now - min(old, new)) mod 1440 < |new - old|` | the old boundary, the local time and the new boundary are all counted from the previous slot's start; refused while the local time lies between the old and the new boundary in those minutes (the owner of that window changes). Correct across midnight |
| the typed value's form at the Apply | `want < 0` only (the Review's parse was trusted through the record) | every copy of the gate re-checks that the record's value is a well-formed HH:MM on the grid, 00:00-23:55 (`want < 2400`, minutes < 60, a multiple of 5): a hand-edited record value such as 2400, which acs1's linear bound refused incidentally, is refused by the gate itself (review finding) |
| refusal texts | "not strictly ascending (unexpected TOU layout)"; "strictly after the previous slot's start and strictly before the next one" | "not one valid 24-hour cycle in slot order (5-minute grid, every slot at least 5 minutes, exactly one wrap past midnight): unexpected TOU layout"; "strictly after the previous slot's start and strictly before the next slot's start, counted round the clock (slot 6 is followed by slot 1)"; "the edit would not leave one valid 24-hour cycle in slot order (...)" |

**Why `cyc2` follows from `cyc` and `order`.** Let the six forward gaps be `g_k >= 5` with `sum g_k = 1440` (`cyc`), `arc = g_(n-1) +
g_n` the window of the edited slot N counted from the previous slot's start, and `uw` the new start counted the same way. The edit
changes only `g_(n-1)` to `uw` and `g_n` to `arc - uw`; with `0 < uw < arc` both are positive, on the 5-minute grid (so at least 5),
and their sum is unchanged, so the proposed layout is one cycle (`cyc2`). Conversely `uw = 0` or `uw = arc` gives a zero gap, and
`uw > arc` makes the two gaps sum to `arc + 1440`, so the total is 2880: `cyc2` fails. Given `cyc`, `order` and `cyc2` are therefore
equivalent. The active-slot guard is exact for the same reason: in minutes counted from the previous slot's start, slot N-1 owns
`[0, b)` and slot N owns `[b, arc)`, so the owner of the current minute changes exactly when it lies between the old and the new `b`.

Everything else is byte for byte as acs1 left it: the 15-minute distance from the old and the new boundary (already circular), the
5-minute grid and the 00:00-23:55 bound of the typed value, the inverter-clock rule (120 s), the UK clock-change-night refusal, every
fail-closed dongle / fallback / Free Power / Dump / RTC / supervision / failback gate, the fresh evidence before the Load, the staged ==
live proof of every non-edited field (the slot's end included), the quiet-window single press, the firmware readback, the two later
reads and the gate-pass counter (+1 exactly), F1 (one Load of slot N-1 after a verified start-time edit; slot 6 for slot 1), F2, F3, F4,
N2 and the UNCERTAIN lock. The value staged and written is still the typed HH:MM on the grid; the "unwrapped" minutes exist only in
comparisons, and no HH:MM above 23:55 can reach the staging number (the Review's parse refuses it, as before).

Two small additions for the owner: the Review notification now names the two slot windows that result ("Slot 5 will then run
23:55-00:25 and slot 4 16:35-23:55"), for which the per-slot entity map gains `live_t_prev` (the previous slot's live start sensor);
and the package header describes the cyclic rule.

A tightening, deliberate and fail-closed: `cyc` requires every one of the six live starts to be on the 5-minute grid (Stage 1 checked
the grid of the typed value only). The firmware's Apply gate refuses any staged start or end off the grid, and the slot's end is the next
slot's start, so an off-grid neighbour would have failed later and less clearly; an off-grid start in the edited slot would make its undo
untypeable. Such a layout is refused at the Review as an "unexpected TOU layout"; target SOC, power and charge-source edits are unaffected.

## 3. Firmware: nothing to change, and why that is known

Read from source at `a7235433` (`firmware/ecco_clock_dongle_stage3_4_free_power.yaml`, which the live S3 image includes unchanged):

- the six starts are single holding registers 250-255 as packed decimal HHMM (0..2359); a slot has no end register (its end is the next
  slot's start; slot 6's end is register 250);
- `apply_manual_slotN` validates each staged time with `valid_hhmm` (0..2359, hh <= 23, mm <= 59, mm % 5 == 0) and `start != end`; it
  has no `start < end` and no cross-slot ordering assumption; the writes are FC16, one register each (232, start, end, power, SOC, flags),
  and the verification reads 232 and the 30 registers 250..279 and compares the five written ones exactly;
- the only ascending check anywhere in scope was the Jinja `asc` of the Home Assistant package.

A start-time write that creates or moves the midnight wrap therefore takes exactly the firmware path a non-wrapping one takes. No
firmware byte, register, write path or timing changes; `test_write_surface_invariants.py` and the chain's firmware metrics are unchanged.
What this does NOT prove: that the real inverter keeps and runs a start-time pair written through this path by the ACS1 editor (no
start-time edit has been applied live through the editor; see section 7). Prior hardware evidence for the firmware path itself: on
2026-09-20 the Manual Controls V1 reversible proof changed register 255 (slot 6's start, slot 5's end) 00:25 -> 00:20 -> 00:25 on this
inverter, VERIFIED OK by exact reread in both directions and confirmed on the inverter's own screen (`registry/inverter_capabilities.yaml`,
the `tou_slot_5_end_time` / `tou_slot_6_start_time` notes), inside the wrap layout. The 25 Oct I3 writes proved the path for power and
charge source with the wrapped pair 22:00 / 00:25 staged. Neither proves that the inverter's scheduler runs the slots correctly after
the midnight crossing is moved to a different slot (section 8).

## 4. Provenance: a second invertible layer, the acs1 record unchanged

The package is generated text. acs1 recorded it as `render_stage1(<Stage 0 text>)` (62 exact pairs, `acs_stage1_transform.py`, pins
`ACS0_BASE_SHA256` / `STAGE1_SHA256` / `PAIRS_SHA256`). acs1c adds `home-assistant/prototypes/acs-stage1/acs1c_transform.py`: 21 exact
`(before, after, count)` pairs applied to the Stage 1 text (`render_cyclic`), invertible (`unrender_cyclic`), with its own pins:

| Pin | Value | Meaning |
|---|---|---|
| `STAGE1_BASE_SHA256` | `2e8813973d133b7bd25fe273af16403af4cea0b8e64b338a015f35412346e9de` | the Stage 1 text the pairs apply to = acs1's `STAGE1_SHA256`, the package installed on 2026-10-25 (site render `1c724e76`): the rollback file of this correction |
| `STAGE1C_SHA256` | the installed package (see `acs1c_transform.py`; asserted by the Stage 1 suite and `_acs1c_scope.py`) | `render_cyclic(<Stage 1 text>)` |
| `CYCLIC_PAIRS_SHA256` | the canonical serialisation of the 21 pairs | a silent edit of any pair is caught |

The acs1 transform, its three pins, its scope module and its chain entry (fingerprint `e0bb9298...`) are byte for byte unchanged. The
installed package is `render_cyclic(render_stage1(<Stage 0 text>))`; `unrender_cyclic(<installed>)` is the Stage 1 text and
`unrender_stage1` of that is the Stage 0 text: both rollback files derive from the installed file alone, without git history. The 21
pairs touch only the gate's ordering lines (four pairs per copy at indents 12 / 12 / 16 / 24), the header's description of the rule,
the Review sentence and the six per-slot map entries; the Stage 1 suite proves that every other line of the Stage 1 text is byte-identical
in the installed package, in the same place and number, and that no pair anchors on, spells or rewrites a line that carries a reserved
fallback / failback token (the 20 such gate lines are inherited untouched; the package still names exactly the six reserved ids acs0's
amendment authorises).

The chain: a new post-export entry `acs1c` is appended after `acu1` (its parent since the rebase onto `main` `07b37c14`; after
`acs1` before that, see section 6), declaring only the files it adds (`acs1c_transform.py`,
`registry/tests/_acs1c_scope.py`, this document) and its fingerprint (`_pex.sealed`); no reverter, no checkpoint (the package is neither
chain-pinned nor frozen, acs1's reasons), no reserved-token holder, no frozen file edited. Edited files that are not hashed: the Stage 1
suite, the Stage 0 suite's loading and provenance lines (the import, the load and the assert; it runs otherwise unchanged on the Stage 0
text recovered through both layers), the PEX ledger in `registry/tests/test_pex_transition.py` (the Stage 1 suite's four extra `_pex`
calls: one fingerprint, one record, two checkpoint), `registry/tests/_scope_chain.py` (the entry), the two acs1 design documents (a note
each), `docs/dev/post-export-edit-layer.md` (a section) and the CHANGELOG. "The installed package" in the transform and the suite means
the package file at the install path once this correction is installed; until then it is the candidate, and the live install is the
Stage 1 site render `1c724e76` of 2026-10-25.

**Publication.** The development history of this correction (three local commits, working-session wording in their messages and
earlier file versions, a personal author address) was never published: the public branch carries one sanitised, DCO-signed commit
with the no-reply identity, whose tree is the accepted one. A later corrective commit would not have removed earlier wording from a
published history, which is why the history was rebuilt rather than amended.

**Rollback of the correction** (after an install, on the owner's authorisation): reinstall the previous site-rendered package (the kit's
backup copy, sha256 `1c724e76` on the host), one reload of the four domains, nothing to restore on the inverter. `unrender_cyclic` of the
installed generic text gives the same generic Stage 1 text (`2e881397`) if a copy is ever needed.

## 5. Tests (offline, all local)

`home-assistant/tests/test_ecco_tou_slot_settings_edit.py` (the Stage 1 suite, now covering both layers; run `python <file>` from the
repository root; about 6 minutes):

- `[0]` provenance of both layers, both ways, pins asserted; `[0c]` the acs1c layer alone: every pair's count, an altered or missing
  anchor refused in both directions naming the pair, the untouched-line proof with mutants, the four gate copies carrying the cyclic
  rule and no trace of the linear one, every literal refusal text within the 255-character input_text frame;
- `[4]` the existing start-time tables unchanged in substance (one expectation flips by design: slot 1 may move to 23:55 after slot 6's
  23:00, one wrap); the layout and malformed-start refusals now name the cycle rule;
- `[4c]` the cyclic rule: the owner's exact baseline with 46 named cases over all six slots (slot 1 <-> 6 and 5 <-> 6 included), its
  six slot rotations, eight kinds of layout that are not one cycle (refused for every slot, other settings unaffected), the active-slot
  guard on a window that crosses midnight (16 cases, both directions), the other start-time guards on the wrap layout, a seeded fuzz of
  96 template Reviews against a plain-Python reference model (`acs1c_transform.verdict`), 20,000 reference-model property cases (its
  cycle rule equals the fallback capture's `ring_valid` plus the grid; the neighbour rule and the proposed-layout rule are equivalent for
  a one-slot change; an accepted edit keeps the other five starts and the 1440-minute partition; rotation invariance), defence in depth
  shown on in-memory mutants, forward and undo Applies on the baseline for every slot (slot 5 across midnight), the three live-proven
  25 Oct edits repeated on the wrap layout (with their write logs: 232, the start, the end register at its unchanged value, power, SOC,
  flags), a neighbour that moves between the Review and the Apply (refused by the fresh-read gate, or applied with the fresh end
  rewritten unchanged), the five-minute slot 6 moved back across midnight (12 active-slot cases), a hand-edited review record refused by
  the Apply's own gate, per-slot checks of the `live_t_prev` map entries and the Review's window sentence, and two independent oracles in
  the property loop (the fallback capture's ring rule for `order`, a ring-based active-slot function for `mid`);
- `[12]` the mutation battery: the linear-rule mutants are replaced and nine acs1c mutants added (both ordering branches dropped; the
  cycle rule dropped; two wraps allowed; a zero-length slot allowed; off-grid live starts allowed; slot 1's previous slot linear again;
  slot 6's next slot linear again; the active-slot guard linear again; the Apply's form re-check back to `want < 0`), each KILLED by a
  failing behavioural check;
- `[13]` the acs1c declaration: position, hash link to acs1, added files, no frozen or chain-pinned edit, pins equal across the suite,
  the transform and the scope module.

Also run: `test_ecco_tou_target_soc_edit.py` (the Stage 0 baseline, unchanged checks), `registry/tests/test_scope_chain.py`,
`test_pex_transition.py`, the four reserved-token suites, `test_write_surface_invariants.py`, `tools/validate_repo.py`,
`tools/analyze_write_surface.py` and `tools/run_offline_tests.py` over `home-assistant/tests` and `registry/tests`. The results of each
run are recorded in the project's review records, outside this repository.

What the suites do NOT prove: anything about a live Home Assistant, the dongle or the inverter; that the real inverter accepts and keeps
a start-time pair written through this path; the Home Assistant time zone (the simulator has one fixed zone); the real clock-change hour.

## 6. Coordination with the dashboard candidate

The dashboard candidate keeps the start-time control disabled and explained until this correction is independently reviewed, installed and
hardware-proven. The UI must then call the existing Review / Apply scripts, never reproduce the gate: the Review's refusal text is the
reason to show. The resulting two windows named in the Review notification ("Slot 5 will then run 23:55-00:25 and slot 4 16:35-23:55")
are the effect line the storyboard asked for. Exposing the start-time editor is a separate, separately reviewed step; nothing in acs1c
enables it.

**Integration with the dashboard branch (correction of an earlier statement).** The dashboard candidate (entry `acu1`) and this
correction (entry `acs1c`) do share files: both append a chain entry after `acs1` in `registry/tests/_scope_chain.py`, both edit the
PEX ledger in `registry/tests/test_pex_transition.py`, and both add an entry at the top of `CHANGELOG.md`. A trial merge of the two
branches reports content conflicts in exactly those three files; no other file is shared (acs1c touches no `frontend/`, dashboard,
manifest or VERSION file; acu1 touches no package, transform, gate or scope module of acs1c). Whichever branch is integrated second
must: rebase onto the other; place its chain entry after the other's and re-seal it with `_pex.sealed` (the fingerprint literal in
`registry/tests/_scope_chain.py`, in its scope module and in its suite; its position in `POST_EXPORT_ENTRIES`); merge the ledger
counts and the CHANGELOG entries by hand; then re-run the `home-assistant/tests` and `registry/tests` roots. Never a silent rebase.
Either order was possible; the dashboard entry `acu1` merged first (public `main` `07b37c14`, 2026-10-26), so this correction was
rebased onto it, its chain entry re-sealed as `acu1`'s child (the three shared files merged by hand) and the suites re-run.

## 7. Deployment and live-test plan (each step needs its own owner authorisation; none is started)

1. **Independent review (a fresh window):** source safety of the 21 pairs and the four gate copies; the equivalence proof; the suite's
   coverage; the chain entry; no weakened guard; the firmware reading of section 3. Done on 2026-10-25 (accepted: logic, tests,
   provenance; the documentation corrections it asked for are in this version).
2. **Dry-run installation preview:** site-render the corrected package (`tools/ecco_site_render.py`, the site's local file), compare
   with the live `1c724e76` (expect exactly the 21 pairs' regions to differ), compute the staged sha256, stage with the existing kit
   procedure (gates first), a fresh FULL backup by the owner, then the install with the four domain reloads (no restart, no inverter
   write; manual write counter unchanged).
3. **Stage 5-type acceptance (read-only):** the start-time Review of the owner's layout is now accepted for an inactive slot (for example
   slot 2 05:30 -> 05:35 in the afternoon), the plan text names the two windows, the review expires unused; SOC, power and source Reviews
   accept as before.
4. **Supervised live proof (separately approved, one step at a time, 5 minutes or more between Applies):** move ONE carefully chosen
   inactive start time by 5 minutes and back, chosen away from the current slot and more than 15 minutes from the local time: for example
   slot 2 05:30 -> 05:35 (register 251; slot 1's end moves with it) in the afternoon. Record before each Apply: the six starts from the
   configuration read, the manual write counter, B10; after each: the firmware's `VERIFIED OK`, the two later reads (start = request,
   end = the next slot's start unchanged, every other register unchanged), the counter +1 exactly, B10 `CONTEXT` after the forward edit
   (slot times are context) and `MATCH` after the undo, F1's Load of slot 1 (its staged end = 05:35, then 05:30), the Manual Controls
   staging of slot 1 refreshed, and the final six starts equal to the baseline. A second proof across the wrap (slot 5 22:00 -> 21:55 ->
   22:00, or slot 6 00:25 -> 00:20 -> 00:25) only if the owner wants it, with the same records; slot 6's forward edit rewrites register
   250 unchanged (slot 1's start) and is therefore a useful register-250 round trip. **Neither of these moves the midnight crossing.**
   Before the dashboard exposes unrestricted start-time editing, a further supervised proof should move the crossing to another slot
   (for example slot 5 22:00 -> 00:05, so that slot 4 runs 16:35 -> 00:05 past midnight, and back) and observe the inverter's own
   scheduler behaviour across that night, not only the register readback; or the dashboard step refuses or warns on crossing-moving
   edits until such a proof exists (section 8). The owner decides which; the gate's safeguards stay as implemented either way.
5. **Rollback** if anything is not APPLIED AND VERIFIED: the editor locks; acknowledge only after the owner has checked the six starts; the
   package rollback is the previous site render (section 4); an inverter value that moved is restored by one more guarded edit, never by
   a compensating write.
6. **Records:** a project status record per live step; the project's status record changes L1 from "fails closed" to "resolved: cyclic
   rule installed and live-proven" only after step 4; the UI step (section 6) follows.

## 8. Residual risks and honest limits

- Adversarial review in this window (three independent reviewers, lenses: the rules against the specification, the safety and
  provenance of the commit, the tests): none refuted the change; their findings (the Apply-side form re-check, fuzz coverage, the
  independent oracles, the write-log assertions, the slot 6 table, the documentation corrections above) are applied in the second
  commit. An independent review by a fresh window followed on 2026-10-25: it accepted the source logic, the tests and the provenance,
  and asked for the documentation corrections that this version carries (privacy wording, this section's residuals, the integration
  note in section 6).

- The real inverter's handling of a start-time write across the wrap by this editor is modelled, not observed (section 3): step 4 is
  the proof.
- **Moving the midnight crossing to another slot (residual).** The gate accepts any valid cycle, so a single edit can move the one
  descent (the slot pair whose next start is earlier) to a different slot: slot 5 22:00 -> 00:05 moves it to slots 4 -> 5 (slot 4
  then runs past midnight); slot 6 00:25 -> 23:55 makes the layout strictly ascending with the descent at slots 6 -> 1. The only
  descent position evidenced on this inverter is the owner's (slots 5 -> 6). The dongle side is position-agnostic (the firmware's
  per-slot check, the Dump conflict check, the fallback ring rule and HA's own schedule-validity sensor all treat the six slots as a
  ring), but the inverter's scheduler behaviour with the crossing elsewhere has not been observed: `APPLIED AND VERIFIED` proves the
  registers hold the request, not which slot the inverter runs at a given minute. Recommendation: a supervised hardware proof of the
  scheduler's behaviour with a relocated crossing (section 7, step 4) before the dashboard enables unrestricted crossing-moving edits;
  until then the dashboard step should refuse or warn on such edits. The safeguards implemented here are unchanged by this note; no
  new write policy is introduced.
- Slot 1's start is also ECCO's "charge start" (`sensor.ecco_config_charge_start_minute` in `ecco_runtime_config.yaml` reads slot 1's
  start as the next regular grid-charge TOU start, feeding the dashboard and the runtime-configuration readiness). This correction
  makes slot 1 editable on the owner's layout for the first time; a slot 1 edit therefore also moves that reading.
- Clock-change nights: the gate still refuses every edit 00:00-03:00 local on those nights, but the cyclic rule allows a start to be
  placed inside the repeated or skipped hour on other days. The firmware's RTC policy reads the live TOU words, so no code is
  affected; the pre-flight for the next clock change (March 2027) must re-read the live starts rather than reuse an older snapshot.
- The cyclic rule tightens one case (an off-grid live start anywhere refuses start-time edits); no such value exists in the owner's
  layout, and the firmware would refuse the Apply anyway.
- The Review notification's extra sentence and the `live_t_prev` map entries are new text in the package: covered by the static scans
  (literal entity ids, existing sensors) and the notification checks.
- Policy P3 ("start times strictly ascending", owner-approved 2026-10-21) is superseded by this cyclic rule only when the owner approves
  it after the review (proposed as P3c); until then the installed package keeps refusing the layout, and the master records L1 as in
  progress, not as mysteriously invalid.
