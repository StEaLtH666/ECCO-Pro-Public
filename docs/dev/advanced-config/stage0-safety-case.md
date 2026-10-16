# Advanced Configuration Stage 0: safety case

**Feature:** a guarded owner edit of ONE TOU slot's target SOC (register 267+N), through the existing firmware manual TOU path
(post-export entry `acs0`).

**Files:**
- `home-assistant/packages/ecco_tou_target_soc_edit.yaml`
- tests: `home-assistant/tests/test_ecco_tou_target_soc_edit.py`, run against the models `_manual_tou_sim.py` and
  `_ha_script_sim.py`

**Status:** offline only. Nothing here is live proof (see the live-proof procedure).

This page answers the owner's additional safety review item by item. Each claim is marked:
- **PROVEN-OFFLINE**: by the suite, against the models;
- **BY CONSTRUCTION**: from the package text, pinned by a static check;
- **BOUNDED**: limited, but not eliminated;
- **RESIDUAL**: a known risk that remains, with how it is surfaced.

## The firmware path and its limits (unchanged by Stage 0)

**What `apply_manual_slotN` does:**
- It refuses unless:
  - the write enable is on;
  - the slot's staging was loaded;
  - the raw configuration cache is valid;
  - the configuration is online;
  - no RTC correction, write lock, Free Power / Dump / register 244 ownership or corrupt lockout is present;
  - the Modbus bus is quiet;
  - the staged values are valid.
- On success it writes 232 (bit 0 composed with the cached register 232), the start/end pair, power, SOC and flags (reserved
  bits preserved). These are sequential FC16 transactions about 700 ms apart.
- It then verifies each register by exact readback and reports `VERIFIED OK` or a failure.

**What it lacks:**
- **No durable snapshot and no rollback.** A failure part-way leaves the registers written so far.
- **Load copies the dongle's configuration cache, not a fresh inverter read.** The cache is refreshed every 60 s.

Stage 0 does not change the firmware. It compensates in Home Assistant, as follows.

## 1. Fresh configuration reads and cache age

- **BY CONSTRUCTION (fresh evidence, not just a connected API):**
  - A live round trip first: the dongle's own **ECCO Supervision Valid Heartbeat Count** must rise after the Apply begins.
    Home Assistant sends a heartbeat every 30 s and the dongle counts each valid one and publishes the count every 30 s, so a
    rise proves Home Assistant -> dongle -> Home Assistant is working now. A frozen view, a dead heartbeat path or a stuck
    dongle loop fails within 90 s: FAILED, nothing pressed.
  - Then a genuinely new poll: `last_configuration_update` (stamped by the dongle's own SNTP clock, published only by a
    completed Block B) must be strictly LATER, as a time, than the value seen after the round trip, and within 120 s of Home
    Assistant's own clock. A replayed or buffered value, a reconnect's re-sent value or an unsynchronised dongle clock fails.
    It refuses if none arrives within 90 s.
  - Every gate (Review, Apply, after the fresh read, just before the press) also refuses unless the dongle's configuration
    time is within 150 s of Home Assistant's clock and the dongle-measured **Heartbeat Age** is known and at most 60 s.
  - The later reads after the Apply must also be within 150 s of Home Assistant's clock.
  - Home Assistant's `last_updated` is not used: an unchanged legitimate state does not update it.
  - On the dongle side the firmware's Load already refuses staging unless the cached TOU values and register 232 come from a
    configuration poll that STARTED after the last staging invalidation (`manual_tou_staging_min_cfg_seq`).
  - It re-runs the full gate on that fresh read, including the shutdown SOC published by the same poll.
  - It refuses unless the Load completes within 30 s of that read.
- **PROVEN-OFFLINE:**
  - An inverter change made after the previous poll (for example on the inverter's own panel) is kept, not reverted.
  - With no fresh read, nothing is written.
  - A late Load is refused.
  - On the happy path the cache age at the Apply press is measured: 17 s in the model (acs0r1; 9.4-19.0 s across the
    phase sweep, section 3b).
  - A frozen view (API up, nothing new published), heartbeats that stop reaching the dongle, a replayed configuration time,
    a dongle clock 10 minutes off (at the Review, or stepping between the Review and the Apply) and an unknown or old heartbeat
    age are each refused before anything is pressed; a dongle clock jump after the write ends UNCERTAIN. Mutants that drop the
    round trip or either clock-coherence check are each caught. A normal edit completes in about 2-3 minutes in the model.
  - The round trip is defence in depth, not a separate proof: with it removed, a frozen view still fails on the strictly-later
    poll and a dead heartbeat on the heartbeat age (the round-trip mutant is caught by its reason, not by a press). Strictly, a
    rise proves Home Assistant received a NEW dongle-counted value after the Apply began; the counted heartbeat itself can be up
    to about 30 s older. The count is RAM-only and rises only for an echo of the dongle's current, single-use challenge, so a
    reconnect re-sends the current value, never history, and a dongle reboot (count back to 0) refuses.
- **Time-zone dependency (bounded):** the dongle stamps polls in local time with no zone (SNTP, Europe/London, `strftime`), and
  Home Assistant's `as_timestamp()` reads a zone-less time in Home Assistant's configured time zone. The editor therefore needs
  Home Assistant configured for Europe/London (the existing Free Power / Dump schedule checks share this dependency); otherwise
  every Review is refused (about 3600 s out in summer time) - fail-closed, but unusable. On the night clocks go back (next:
  25 Oct 2026) the repeated 01:00-02:00 hour parses an hour out: edits are refused during it, and an Apply running across the
  change would see its later reads go backwards and end UNCERTAIN and locked. Do not edit around 01:00-02:00 that night.
  The offline model uses one fixed zone for both sides, so it cannot test this; the live-proof preconditions check it.
- **BOUNDED:**
  - The cache is under 30 s old at the press: the Load within 30 s of the fresh read, and acs0r1's press within 25 s +
    1.5 s + the arm (at most 4.5 s after a completion that is at most 25 s after the fresh read).
  - Within that window, a change made by another Modbus master to slot N's start/end/power/SOC/flags or register 232 would be
    rewritten with the cached value. The documented second master (SmartDeye) must not be used concurrently.
  - Detection: the independent later read compares every written register with its pre-edit value, but a value reverted to
    exactly its pre-edit state cannot be detected. This is RESIDUAL and documented.

## 2. Other automations changing staged values

- The Manual Controls helper package (`ecco_manual_controls_helpers.yaml`) mirrors the friendly helpers and the firmware's
  staging numbers in both directions, and refreshes all helpers 2 s after any Load.
- **BY CONSTRUCTION:** before staging and again before arming, the edit waits for a FIXED POINT:
  - the refresh script is not running;
  - slot N's start-time, power and SOC helpers equal the staging numbers, so every sync automation would be a no-op;
  - every staged field except the SOC equals the live slot.
- **PROVEN-OFFLINE (with the REAL helper package running in the simulator):**
  - Stale helpers converge.
  - An owner edit of a helper mid-flow, which the sync pushes into staging, stops the edit with nothing pressed.
  - The edit also works without the helper package.
- **BOUNDED:** the last check and the press are consecutive steps of one script. An automation scheduled between them is the
  only window, and is not excluded by construction. Its effect would appear in the independent later read and lock the
  editor.

## 3. Changes between validation, Load, arm and Apply

- **BY CONSTRUCTION:** the full fail-closed gate runs four times:
  1. at Review;
  2. at Apply start;
  3. on the fresh read;
  4. immediately before the press, with the bounds re-read: max(inverter shutdown SOC, ECCO reserve).

  The review is single-use, expires after 10 minutes, and is invalidated if the slot's live SOC changed since.
- **PROVEN-OFFLINE:** every unsafe state was injected:
  - Free Power / Dump active, transaction or restore owed; register 244;
  - recovery arms and evidence; containment;
  - the fallback system armed for an operation (the status package's Save / Replace Corrupt / Invalidate Available sensors),
    and a fallback Review or Save in progress;
  - the `obl=` lease field; supervision and failback shadow;
  - RTC correction; manual write;
  - schedules within 15 minutes;
  - the lock.

  Each was injected both as its unsafe value and as `unavailable`, at Review (82 cases), between Review and Apply, and after
  the Load (RTC, supervision, reserve raised, Free Power). Every case refuses or stops before the press.
- **BOUNDED:** the firmware gate re-checks its own interlocks at the press. A change after the press is the firmware's to
  refuse.

## 3b. The press and routine Modbus polling (acs0r1)

- **LIVE EVIDENCE (2026-10-16, S3, firmware `d1c9a3e1`):**
  - the firmware's Apply gate refuses while ANY frame is queued or in flight (`!tx_buffer_empty() || tx_blocked()`),
    routine reads included;
  - the pre-acs0r1 Apply pressed a fixed ~5.3 s after the configuration read. Both 99 -> 100 % restores were refused,
    nothing written:
    - B2's refusal (17:06:09.602) came within the telemetry poll's last frame, whose publish was seen at 17:06:09.624;
    - B1's refusal (17:00:09.692) reached Home Assistant 1 ms AFTER the telemetry publish (17:00:09.691). So the bus can still
      be busy right after a completion: a publish can arrive in the same API batch as a frame still running, or another
      frame follows.
  - The 100 -> 99 % edit succeeded only because its Load was answered 7.3 s late.
- **BY CONSTRUCTION (acs0r1):** no offset from the configuration read. Every time used is observed by the Apply itself:
  - **Step 0, before the fresh evidence** (the cache age is unaffected):
    - one inverter clock read (Inverter Time changes; a 0.3 s frame once a minute) gives its phase;
    - two CLEAN telemetry completions (Last Telemetry Update valid and strictly later; an `unavailable` blip or a reconnect's
      re-sent value does not count) give its period, which must be at least 8 s.
    Either not observed: FAILED at the fresh-evidence check, nothing pressed. A stalled inverter clock or a dropped publish is
    never taken to mean "no bus user".
  - **Step 3b, after the staging:**
    - the press follows a clean completion x by **1.5 s**, the middle of the gap, never at the completion;
    - x qualifies only if the window [x, x + 5.0 s] holds no clock read and x is at most 25 s after the fresh read;
    - the next telemetry frame is at x + period - 2.8 s >= x + 5.2 s;
    - this minute's configuration blocks ended before the staging, and the next minute's begin about 57 s after the fresh
      read;
    - a second completion is tried, otherwise FAILED, nothing pressed;
    - the press must follow the completion within 4.5 s.
- **UNCHANGED:** exactly one press; a firmware refusal is final; the gates, the fresh evidence, staged == live and the
  independent later-read verdict.
- **PROVEN-OFFLINE (suite section 13):**
  - the pre-acs0r1 package, reconstructed exactly (sha256-pinned to main `1332decf`), reproduces against the dongle model's
    bus timeline (calibrated to the live offsets):
    - B2 exactly (a press inside the telemetry poll's last frame);
    - a B1-type refusal (the gate 0.1 s after the publish, in a post-publish tail);
    - an A-type success (a late Load: model +9.6 s, live +13.1 s);
    - the whole live sequence (slot 1 left at 99);
  - acs0r1 applies all of them, including a bus busy for up to 1.2 s after the publish;
  - sweeps: 25 telemetry phases, 20 clock-read phases, a 20-point configuration x telemetry grid, and arm latency 0.05-2.6 s
    x press latency 0.05-0.4 s;
  - changed poll timing: telemetry periods of 12 s (applied) and 5 s (FAILED, nothing pressed); no clock read seen and a
    stalled clock (both FAILED, nothing pressed); telemetry `unavailable` blips and re-sends (ignored); telemetry stopping;
  - the cache age at the press is 9.4-19.0 s across the sweep (bound < 30 s);
  - seven targeted mutants are each caught. Without the clock exclusion, a press at the live offsets lands on the clock read's
    frame.
- **BOUNDED / RESIDUAL:**
  - A bus user the model does not schedule can still meet the press: an RTC correction write, a catch-up configuration poll,
    or a post-write refresh used as the fresh read. The firmware then refuses, nothing is written, the outcome is FAILED, and
    the owner Reviews and Applies again.
  - The cause of B1 (a frame after the publish, or the publish batched early) is not proven. The 1.5 s offset covers both up
    to a 1.2 s tail; the dongle logs (`esphome logs`) during the next live proof should show it.

## 4. Partial multi-register writes

- **BY CONSTRUCTION:** the only staged value that differs from the live inverter is the target SOC. The other staged fields
  are proven equal to the live slot at the fresh read.
- **PROVEN-OFFLINE (model only):** a partial write stopping after each of the 6 transactions leaves every register except
  the SOC at its value, and the outcome is UNCERTAIN, locked and alerted.
- **NOT PROVEN, explicitly bounded:** the claim "an interrupted live write can only affect the SOC" depends on assumptions
  that the offline suite cannot prove:
  1. the cache values written back equal the inverter's current values (bounded by section 1);
  2. each FC16 transaction is applied atomically by the inverter or not at all, with no torn multi-register write of the
     start/end pair;
  3. the inverter does not clamp or transform a rewritten value.

  None of these is proven on this inverter. Therefore:
  - Stage 0 never treats an interrupted or unverifiable write as harmless. It always ends UNCERTAIN, locked, with a manual
    review.
  - The live-proof procedure includes checks of every slot register after each step.

## 5. Independent read-back of every affected register

- **BY CONSTRUCTION:** success requires ALL of:
  - the firmware's `VERIFIED OK - manual Slot N` (its own readback);
  - TWO later configuration polls after the outcome. The first may be the firmware's own post-Apply poll, which reads Block A
    about 0.9 s after the verify, waits 2.5 s, reads Block B, and only then publishes. The second is a poll that began after
    it: the firmware runs one poll at a time (`mode: single`), skips Block B while its write lock is held, and publishes the
    update time only from a completed Block B.
  - The reads are compared as TIMES (Last Configuration Update, `%Y-%m-%d %H:%M:%S` from the dongle's synchronised clock),
    each strictly later than the one before. A connection drop's `unavailable` and the value a reconnect re-sends are not
    reads. A clock step backwards, or an unsynchronised clock ("Waiting"), ends UNCERTAIN.
  - Configuration Online and the raw configuration cache valid at that read. Block B publishes the update time even when
    Block A failed, and register 232 comes from Block A.
  - In that read:
    - the SOC equals the request;
    - slot N's start, end (the next slot's start), power, charge source, mode, raw flags and the grid-charge bit all equal
      their pre-edit values.
- **PROVEN-OFFLINE (the model now publishes the firmware's post-Apply poll at +3.9 s, as the real firmware does):**
  - Only the firmware's own poll arriving: UNCERTAIN.
  - A connection drop after the outcome whose reconnect re-sends the firmware's own poll time, with no later poll: UNCERTAIN.
    With the periodic polls continuing, the same drop still verifies, on a poll that began after the firmware's own.
  - An invalid raw cache at the later read: UNCERTAIN.
  - A verified write whose later read shows another register changed: UNCERTAIN, and the alert lists the field.
- **RESIDUAL:** register 232's bits other than bit 0 are not exposed to Home Assistant, so they are not independently read
  back. The firmware preserves them from its cache.

## 6. Ambiguous outcomes

- **BY CONSTRUCTION:**
  - One press per request, never retried, never a compensating write.
  - The write enable is turned off as soon as the firmware's 45 s window ends (the firmware reads it only at its Apply gate,
    so this cannot interrupt a write), and again at the end, where it must be SEEN off within 10 s; otherwise the outcome
    is UNCERTAIN (the text keeps the earlier outcome). Home Assistant skips service calls to an unavailable entity, so
    `continue_on_error` alone proves nothing.
  - "The firmware refused, nothing written" is claimed only when ALL hold:
    - the result text is a refusal;
    - the firmware's gate-pass counter (Manual Configuration Write Attempts Since Boot) did not move over 35 s;
    - the two later reads show every written register at its pre-edit value.

    Otherwise the outcome is UNCERTAIN. A later refusal text from an unrelated press can no longer hide a real write.
  - An Apply holds `input_boolean.ecco_cfg_edit_in_flight` (restored across restarts) from before its first press until its
    outcome is judged. Review and Acknowledge refuse while an Apply runs or is in flight, and touch neither the result, the
    plan nor the marker; an Apply refuses while an earlier run is in flight.
  - A run interrupted before its outcome was judged (a Home Assistant restart or a script reload) leaves the marker on. The
    package's one automation (`ecco_cfg_edit_interrupted`) fires on Home Assistant start, and when the marker is on while
    the Apply script is off. It locks, marks the outcome UNCERTAIN and alerts AT ONCE (so nothing can start in the window
    before the dongle reconnects), clears the marker, then waits up to 10 minutes for the write enable to become reachable,
    turns it off and confirms it reads off; otherwise a separate "NOT confirmed off" alert.
  - Any outcome other than "firmware refused at its gate" or "verified twice" is UNCERTAIN. That covers a failed verification,
    a partial write, a clamp, a disagreeing or missing later read, and a dropped or unanswered press.
  - UNCERTAIN sets `input_boolean.ecco_cfg_edit_review_required`, which refuses every later Review and Apply until the owner
    runs `script.ecco_cfg_acknowledge_edit_review` with the exact phrase `I HAVE CHECKED THE TOU SLOTS`.
- **PROVEN-OFFLINE:** each case above locks, including a stuck write enable, an unrelated refusal text after a real write,
  a partial write of unchanged values hidden by an unrelated refusal (only the counter shows it), an HA restart mid-edit
  (locked within a second, while the dongle is still unavailable; a Review or Apply in that window is refused; the write
  enable confirmed off once the dongle returns, or a separate alert), a cancelled run, and a Review or Acknowledge during an
  Apply; only the exact phrase unlocks. A press that never arrives leaves the write enable on for at most about 50 s.

## 7. Notifications and recovery instructions

**BY CONSTRUCTION:**
- **On UNCERTAIN:** a persistent notification gives:
  - the requested change;
  - the firmware's own result text;
  - the independent read, listing every field that differs with its observed and pre-edit values, or "no new configuration
    read";
  - the recovery steps: do not retry; Load the slot in Manual Controls and compare with the inverter's own display; correct
    deliberately; settle the slot before Free Power or Dump to Grid snapshot it; acknowledge to unlock.
- **On a firmware refusal:** a "nothing written" alert.
- **On success:** a DRIFT notice (Review and Save the fallback profile if this is the new normal) and the undo (the same
  guarded edit back to the old value).

## Scope

**BY CONSTRUCTION, pinned by static checks:**
- `number.set_value` appears exactly once, on the slot's target SOC staging entity.
- `button.press` appears exactly twice: the slot's Load and Apply.
- `switch.turn_on` only on the Manual Configuration Write Enable.
- No ESPHome action, Modbus service, select, input_number write or register path.
- The reserve helper is only read.

The firmware write surface is unchanged.

## Fallback gate: what it covers

The gate reads six reserved fallback / failback entity ids, and nothing else of the fallback system. Each check is exact and
fails closed: an unknown, unavailable, empty, malformed, duplicated, stale or unexpected value refuses the edit.

| Id | Must read exactly |
|---|---|
| Live match (B10, `sensor.…_ecco_fallback_profile_live_match`) | every key `m`, `obl`, `ca`, `eh` once; `obl=FP:CR,DP:CR,R4:CR,BUS:OK` (no lease, restore, lockout or register 244 transaction; bus idle); `ca=F` (a fresh, trusted cache: not boot, invalid, polling off, stale, pre-fence or unfilled); `eh=0` (export hazard ruled out); `m` = `MATCH`, `DRIFT` or `CONTEXT` (a comparison actually ran) |
| Fallback Review (B3, `sensor.…_ecco_fallback_profile_review`) | exactly one `st=` field, and it is `IDLE` |
| Save / Replace Corrupt / Invalidate Available (`binary_sensor.ecco_fallback_*_available`) | `off` |
| Failback shadow State (`sensor.…_ecco_failback_shadow_state`) | `SHADOW_IDLE` |

The firmware publishes `MATCH` / `DRIFT` / `CONTEXT` only when the boot load is complete, every lease is clear, the bus is idle
and the cache is fresh. `UNKNOWN`, `PAUSED` and `PAUSED_IO` mean the comparison did not run, and refuse.

**A deliberate fail-closed choice (owner decision point):** three further verdicts also refuse, and the refusal names the verdict.
- `NO_PROFILE`: no VALID saved fallback profile. It also covers a corrupt profile and a fallback write whose outcome is unknown,
  which is why it refuses. **Consequence:** the editor cannot be used on an installation without a saved profile, or after an
  Invalidate, until a profile is saved.
- `EXPORT` (a trusted comparison: live register 244 allows export where the saved profile does not) and `OUT_OF_DOMAIN` (a trusted
  comparison: a live value outside the profile's value domain, for example a slot power below its minimum). **Consequence:** while
  the inverter is in either state the editor refuses until it is put right through the normal tools.
- The editor itself can never cause these: it changes only a slot SOC (always inside the domain) and never register 244, so the
  only verdict it produces is `DRIFT`, which is allowed (step B of the live proof starts in `DRIFT`).
Allowing `EXPORT` or `OUT_OF_DOMAIN` would be a one-line change to the verdict list; it was not made without the owner's decision. The live S3 evidence shows `MATCH` / `DRIFT` with
`ca=F`, `eh=0` in steady state; `UNKNOWN ca=P` and `PAUSED_IO BUS:BY` appear only transiently around writes and bus activity,
where refusing is correct.

**Proven offline:** 56 ambiguous states (each verdict and cache letter, hazard `U` / `1`, case and whitespace variants,
duplicated keys, a prefixed key, an extra lease leg, empty and `unknown` values for every id) are each refused, and `DRIFT` /
`CONTEXT` still allow the edit. Mutants that drop the freshness, the verdict or the duplicate check are each caught.

**Home Assistant-side staleness (closed by the fresh-evidence gate, section 1):** ESPHome publishes a text sensor only when it
changes, so an unchanged live-match text is not evidence of anything by itself. The Apply therefore proves a live round trip
(the dongle-counted heartbeat rises) and a genuinely new, clock-coherent configuration poll before it Loads. The live match is
recomputed in the same single-threaded dongle loop every 10 s, so with the loop and the publish path proven live it is at most
one tick old. Residual: the dongle's own logic is trusted (a firmware that kept counting heartbeats and polling while its
live-match computation alone was wedged is not detected), and both clocks must be NTP-synchronised (an unsynchronised clock
refuses rather than passes).

**Bounded, not proven:** the three operator "available" sensors are Home Assistant templates. If their own inputs (the arm, the
profile state, the Review id) were unavailable while the dongle stayed connected, they would read `off`. With the ESPHome native
API a device's entities become unavailable together, which the gate refuses through Telemetry / Configuration Online; and the
Save / Replace paths also need `st=CANDIDATE_READY`, which the direct Review check refuses. The package must not name the fallback
arm (a frozen test reserves it to the fallback packages), so this is documented rather than checked directly.

### The reserved-token amendment (owner-approved Option A, 2026-10-12)

The FB-A / FB-B3 / FB-C3 token rule allows reserved tokens (`ecco_fallback`, `ecco_failback`, `FALLBACK_PROFILE`,
`FAILBACK_STATE`) only in files a chain entry declares, and five exact allowlist checks pin today's holders. Entry `acs0`:
- declares exactly its three files as reserved-token holders: the package, its dongle model and its suite;
- amends the five checks so that, in exactly those files, exactly the six ids above (spelled in full, word-bounded at both ends)
  are exempt. Nothing is widened for any other file, id or operation:
  - `test_fallback_profile_schema.py` (frozen, PEX): the FB-C3 strict rule exempts only the shadow State id in the three files,
    with its own exactness proof; the exact declared allowlist grows from eight to eleven named files;
  - `test_fallback_recovery_dashboard.py` (frozen, PEX): the FB-B3 holder list is unchanged; the six ids are removed from the
    package before the scan, with an exactness proof (a seventh id or a variant still makes it a holder);
  - `test_fallback_save_scope.py` (frozen, PEX): the exact union of declaring entries gains `acs0`, pinned to its three files;
  - `test_fallback_live_match.py` (not frozen): the B10 holder list is unchanged; the full B10 id is removed from the three
    files before the scan, with an exactness proof.
- The editor's own suite (section [12]) proves every occurrence in the package is inside `states()` / `is_state()` (24: six ids
  in four gate copies), that no indirect route exists (no `state_attr`, `states.<domain>`, `expand`, `*_entities`, built entity
  ids, or the status package's other sensors by name), and that eleven evasions in the package and the ids in any undeclared
  file are refused. Where exactness is enforced: the FB-C3 strict rule and the B10 scan in all three files, the FB-B3 holder scan
  in the package, and the editor's suite for any other ecco_fallback-family id in the two `.py` files (`banned_files` is a
  whole-file declaration, as in every earlier entry).
- Tamper proofs (run on scratch clones during review, not part of the repository) ran the real suites against a seventh id, another
  shadow id, an undeclared holder, a write, an indirect read, a widened frozen regex, a dropped declaration and a removed freshness
  check; each was refused.

**If the status package is not installed,** the three operator sensors read `unknown` and every edit is refused (fail-closed,
but the feature is then unusable).

## Other residual points (accepted, documented)

- **The shared write enable (documented, not changed).** The firmware has ONE Manual Configuration Write Enable for every
  manual write path (slot 1-6 Apply, the register 244 proof). Stage 0 holds it on for about 5-15 s per edit (at most about 50 s
  if the press is lost: the 5 s wait to see it on plus the firmware's 45 s window). Within that window:
  - an Apply the owner presses by hand in Manual Controls (another loaded slot, or the register 244 test) would consume it.
    The firmware's write lock serialises the two writes: this edit either refuses before its own press, or is judged as usual
    by the firmware readback and its two later reads of its own slot. A "refused, nothing written" claim is withdrawn
    (UNCERTAIN, locked) whenever the gate-pass counter moved for any reason, so the other press can never make this edit
    report a false refusal. The other write is the owner's own, through the existing firmware path and its own gate;
  - Stage 0 cannot disable the dashboard's Manual Controls without widening the write surface, so the procedure is
    operational: do not use Manual Controls while an edit is IN PROGRESS (the in-flight marker is on). Stage 0b can hide or
    disable those controls while the marker is on, as a display-only change.
- **Admin unlock (documented, not changed).** The manual-review lock (`input_boolean.ecco_cfg_edit_review_required`) and the
  in-flight marker (`input_boolean.ecco_cfg_edit_in_flight`) are ordinary helpers that a Home Assistant administrator can
  switch in the UI:
  - switching the lock off skips the acknowledgement phrase and re-enables edits after an UNCERTAIN outcome, without the TOU
    slots having been checked;
  - switching the in-flight marker off during an Apply hides an interrupted run from the watchdog.
  Authorisation is the Home Assistant login (an administrator can also edit the package itself). Mitigation is procedural:
  only the acknowledgement script clears the lock. A detection-only audit automation (alert, never re-lock, when either helper
  changes outside the editor's scripts, by the change's context) is a candidate for Stage 0b; it is not part of this change.
- **Load overwrites staging.** The Load overwrites slot N's unsaved Manual Controls staging and the shared grid-charge
  staging switch, with the live values.
- **The review code.** It is time-derived: a typo and freshness guard, not an authorisation. Authorisation is the Home
  Assistant login.
- **An unclean crash.** Home Assistant saves restorable state every 15 minutes and on a clean stop. After a crash or power
  loss it can restore an older in-flight marker, so an Apply interrupted that way may go unnoticed. The watchdog's claim is
  limited to clean stops, restarts and script reloads. The live-proof procedure is supervised throughout.
- **A refused Review while locked** replaces the visible UNCERTAIN text with "REVIEW REFUSED - an earlier edit's outcome
  needs manual review first"; the lock and the UNCERTAIN alert remain.
- **Run length.** About 2-3 minutes typically, about 10 minutes at worst (every wait timing out, including the 90 s round
  trip). The last schedule check is just before the press and at most about 6.5 minutes follow it, inside the 15-minute
  Free Power / Dump schedule guard.
- **Non-integer inputs.** These are truncated (slot 1.5 → 1, SOC 55.9 → 55). The review shows the resulting values before
  anything happens.
