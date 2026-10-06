# ECCO Fallback / Recovery Card

A Lovelace card for the **Fallback / Recovery** tab of the ECCO Pro dashboard. It is the
operator surface for **FB-B1: Review Current Configuration** (a read-only review of the
inverter's fallback-profile registers) and, since **FB-B2**, for the guarded **Save** and
**Invalidate** of the saved Fallback Profile.

- It reads the dongle's Fallback Profile text entities and shows eight cards: Saved Profile,
  Live Match, Review Current Configuration, Candidate, Save Readiness, Configuration Summary,
  Advanced raw values and a reserved Recovery area.
- A review reads the inverter twice (four reads) and changes nothing - no inverter write, no
  storage write.
- **Save** and **Invalidate** write the profile record in the dongle's own storage (never the
  inverter) and only through a guarded flow: *Arm Save* (or *Arm Invalidate*), a confirmation
  panel that names the exact ID, then one explicit click. See [Save and Invalidate](#save-and-invalidate-fb-b2).
- There is **no** restore control. The Restore tile in the Recovery area is a ghost and stays
  inert (FB-E, FB-F). Nothing on this card writes the inverter.

One dependency-free ES module: no build step, no npm packages, no network access.
It needs a current browser: `Object.hasOwn` (Chrome 93, Firefox 92, Safari 15.4) and CSS container
queries (Chrome 105, Firefox 110, Safari 16), which is what Home Assistant's own frontend requires.

The visual design follows the saved Fable design (kept with the architecture docs, not part of this
change set): a mockup page and a written specification. In this README "the mockup" and "design
section N" mean those two. The card reuses the ECCO dashboard's ground, state colours and radius.
Every place where it deliberately differs from the mockup or the specification is listed, with the
reason, under [Deviations from the mockup](#deviations-from-the-mockup).

## Install

1. Copy `ecco-fallback-recovery-card.js` to Home Assistant's `/config/www/ecco/`. From the
   repository root:
   ```powershell
   .\tools\deploy-ha.ps1 frontend\ecco-fallback-recovery-card\ecco-fallback-recovery-card.js `
     -Destination /config/www/ecco/ecco-fallback-recovery-card.js
   ```
   The file is served back as `/local/ecco/ecco-fallback-recovery-card.js`.
   `deployment/ha-manifest.yaml` lists the card under `frontend_assets` for the deploy tooling
   only: copying the file and registering the resource are both manual steps. The manifest's own
   comment still describes the FB-B1 stage ("read-only review ... NOT deployed"); it is a pinned
   artifact and was left untouched by FB-B2, so read that comment as history. Nothing in this
   change set is deployed.
2. Register it as a Lovelace resource - **Settings -> Dashboards -> Resources -> Add Resource**,
   URL `/local/ecco/ecco-fallback-recovery-card.js`, type **JavaScript Module**. This step is
   always manual.
3. Add the card (see Configuration), or pick "ECCO Fallback / Recovery Card" from the card
   picker (it registers itself through `window.customCards`).

**After copying a new version of the file** (for example the FB-B2 card over the FB-B1 one), Home
Assistant and the browser keep serving the old module from their caches. Either do a hard refresh
of the dashboard (Ctrl+Shift+R, Ctrl+F5 or the browser's "empty cache and hard reload"; on the
Home Assistant mobile app clear the app cache), or change the Lovelace resource URL to carry a
version, for example `/local/ecco/ecco-fallback-recovery-card.js?v=0.2.0`, and bump it with every
release. The `resource_url` in the deployment manifest cannot carry the `?v=`; the resource you
register in the Home Assistant UI can. The card reports its version in `VERSION` (0.2.0 for FB-B2).

## Configuration

Every entity id comes from the configuration; the card never hard-codes one. The ids below are
placeholders - use the ids of your dongle's entities.

```yaml
type: custom:ecco-fallback-recovery-card
title: Fallback / Recovery           # optional, default "Fallback / Recovery"
show_header: true                    # optional, default true: title and Supervision / NTP / Write lock badges
entities:
  # required - the nine Fallback Profile text entities and the Review button
  profile_state: sensor.example_profile_state        # class: NOT_CAPTURED VALID INVALIDATED ...
  summary: sensor.example_summary                     # g= id= at= ld= df= w= hw= op= why= werr= us=
  review: sensor.example_review                       # st= prior= exp= warn= obl= latch= sv=
  review_id: sensor.example_review_id                 # 16 hex digits while a candidate is saveable
  review_slots: sensor.example_review_slots           # candidate slots  (v=CAND|NONE)
  review_context: sensor.example_review_context       # candidate context (v=CAND|NONE)
  saved_slots: sensor.example_saved_slots             # saved slots   (v=SAVED|NONE, b=)
  saved_context: sensor.example_saved_context         # saved context (v=SAVED|NONE, b=)
  last_result: sensor.example_last_result             # "<OUTCOME> - <detail>"
  review_button: button.example_review_button         # the button the card presses to start a review
  # optional - badges and the save prerequisites (supervision, trusted time, bus)
  supervision_stable: binary_sensor.example_supervision_stable
  supervision_state: sensor.example_supervision_state
  ntp_synced: binary_sensor.example_ntp_synced
  write_lock: binary_sensor.example_write_lock
  configuration_online: binary_sensor.example_configuration_online
  # optional - the Save / Invalidate flow (FB-B2). Without `arm` the card stays review-only.
  arm: switch.example_arm                             # the Fallback Profile arm: the card switches it from a user click
  free_power_arm: switch.example_free_power_arm       # read-only: the dongle refuses a save while one of these three
  dump_arm: switch.example_dump_arm                   # write arms is on (the card only reads them to say so early)
  manual_arm: switch.example_manual_arm
# optional - share the "technical detail" expand state across browsers (see below)
technical_detail_entity: input_boolean.example_detail
```

Inside a Home Assistant sections view give the card the full row:

```yaml
grid_options:
  columns: 48     # a column_span 4 section
  rows: auto
```

Configuration is validated when the card loads: a missing required entity, an entity of the
wrong domain (for example a `switch.` as `review_button`) or an unknown key raises an error
that names the offending key. The four arm keys must be `switch.` entities, and **one entity id may
serve only one key**: the card turns `entities.arm` on from a click, so an id that is also one of the
three write arms (or any other key) is refused when the card loads, and the allow-list refuses the
arm and execute calls for a configuration object that names the arm twice. Leaving an optional
key out is fine: the checks that need it read **unknown** (the dongle checks it when you save)
instead of blocking, except `arm` itself: with no arm entity the Save and Invalidate controls are
shown disabled with the reason "not set up on this dashboard".

`show_header: false` hides the card's own title and badge row. The ECCO dashboard does this
because its section already starts with a Home Assistant heading card that carries the same
three badges.

## What the card shows

| Card | Source | Notes |
|---|---|---|
| 1 Saved Profile | `profile_state`, `summary`, `arm` | SAVED, NOT SAVED, INVALIDATED, UNUSABLE (six sentences), NOT REPORTING. For a VALID profile: Arm Invalidate, its confirmation panel and the last Invalidate outcome |
| 2 Live Match | `review_slots`, `review_context` masks | Derived **only** from the latest review while a candidate exists; otherwise UNKNOWN. There is no continuous match. See "Live Match wording" below |
| 3 Review | `review`, `last_result`, `review_button` | Four-step progress (SAVING shows `Commit` as the last step), countdown, the Review button, the last action line |
| 4 Candidate | `review`, `review_id`, slots, context, `arm` | ID with copy button, age, expiry, blockers and warnings; Arm Save, the confirmation panel, the save request, the last Save outcome |
| 5 Save Readiness | `review`, supervision, NTP, arms | Six checks. Checks 5 and 6 are **save** prerequisites; they never block a review. The footer adds what the six checks do not cover |
| 6 Configuration Summary | candidate or saved views | Candidate / Saved selector, diff markers, slot table |
| 7 Advanced | all entities | Hidden until "Show technical detail"; the 31-register table, raw entity strings with copy buttons, the obligation vector and the probe latch |
| 8 Recovery | none | Three ghosted tiles (Restore Saved Profile, Recovery Hold, Validated Resume) for later stages |

### Save and Invalidate (FB-B2)

The flow is deliberately slow and explicit. Every step is a separate user action, the card never
retries, and the dongle checks everything again.

#### Save

1. **Review.** Press *Review Current Configuration*. A candidate appears (ID, countdown, values).
   A review also turns the arm off.
2. **Arm Save.** In the Candidate card, *Arm Save* is enabled when everything except the arm
   passes. If not, it stays on screen, marked `aria-disabled`, with the reason as a tooltip and as
   a visible line. Pressing it calls `switch.turn_on` on `entities.arm` and nothing else. The
   card waits for Home Assistant to **report** the switch on: the confirmation is never
   optimistic. The arm turns off by itself after 2 min (the dongle applies the limit on its 10 s
   tick, so up to about 130 s), and whenever you press Review, Save or Invalidate.
3. **Confirmation panel.** It opens only for an arm **this card** switched on for a save (an arm
   that is on for any other reason shows the strip described below), and stays open while the arm
   reports on and a ready candidate is shown. It names the **ID being confirmed** (the 16 hex digits of the candidate, as on
   screen), what the save does (first save, replacing the saved profile with its generation,
   replacing a lost or stale one, or replacing a **damaged** profile), the expected generation,
   the exact confirmation phrase that will be sent, every prerequisite with its state word and
   its blocking reason, and a live **arm timer** (it counts down in place: the markup does not
   change each second). Prerequisites: arm on, no other Fallback Profile operation running,
   candidate saveable, candidate not expired, stored profile can be replaced, Home Assistant
   heartbeat stable (state SUPERVISED **and** a stable run), trusted time, no other write arm on,
   bus idle, no temporary operation active (as of the review). A prerequisite the card cannot
   judge because its optional entity is not configured is **unknown** and does not block. Two
   things the card needs in order to show you what you are confirming are **unknown and blocking**:
   the candidate values (the review slots and context entities must be readable as a candidate) and
   the saved-profile summary (without it the "Expected generation" cannot be derived, so none is
   printed: the panel says it cannot be shown instead of guessing "generation 1"). A candidate
   whose time left is not known (no valid `exp`) cannot be saved either.
   Buttons: *Save Fallback Profile* (or *Replace damaged profile* for a CORRUPT stored profile,
   which sends the `REPLACE CORRUPT` phrase) and *Cancel* (turns the arm off). Keyboard focus
   moves to the panel heading when it opens; the Save button is never focused for you.
4. **Save.** One click sends exactly one request: the execute action
   `esphome.ecco_clock_dongle_fallback_profile_execute` with `action: SAVE`, `target_id` = the
   candidate ID that was on screen when the button was drawn, `confirmation` = `SAVE <ID>`
   (`SAVE <ID> REPLACE CORRUPT` for a damaged prior). If the current candidate ID is not the one
   on the button, or any prerequisite no longer holds, **nothing is sent** and the card says so.
5. **Request sent.** *Request sent - waiting for the dongle.* with a busy indicator
   (`aria-busy`); the panel and its buttons are gone, so there is no second submit, and Review is
   held (*Save in progress*).
6. **Saving.** The dongle reports `st=SAVING` (card 3 headline SAVING, card 4 SAVE IN PROGRESS).
   The candidate ID and the expected generation stay on screen.
7. **Result.** The last-action text decides, together with the profile entities:
   - `SAVED - ... (verified this boot)`: shown as **Saved and verified this boot** only when the
     profile class is VALID, the generation in the summary equals the generation in the text, the
     summary's witness reads OK (`w=OK`), it reports no storage error (`werr=-`) and its last
     operation is the save (`op=SAVE`, or `op=RC` after a REPLACE CORRUPT save); otherwise the card
     says it is waiting for the saved profile to update. An invalidate is judged the same way
     (`INVALIDATED`, `op=INV`).
   - `SAVE REFUSED - <reason>`: the dongle's reason, verbatim. Nothing was saved; the arm and the
     candidate are used up, so review again.
   - `SAVE NOT COMMITTED - ...`: storage refused the write (nothing changed), or the generation
     record advanced and the stored profile is now out of step (review and save again).
   - `SAVE OUTCOME UNKNOWN - ...`: **do not press Save again.** If a temporary operation (Free
     Power, Dump to Grid, register 244 test) is active or needs a decision, do not restart the
     dongle; otherwise restart it to find out what was stored. The Saved profile card shows the
     class SAVE_UNCONFIRMED and saving stays disabled until the dongle restarts.

**What ends a pending request.** The dongle's answer: the review state leaves `CANDIDATE_READY`
(the candidate was used up), or the last-action text changes. The arm turning off is **not** an
answer by itself: the dongle publishes it before the review state and the last action, and Home
Assistant may deliver them as separate updates, so on its own it ends a request only after the arm
has stayed off for 5 s with nothing else said (a repeated identical outcome changes no entity at
all). A periodic re-publish of the same state is never an answer. The 30 s limit is evaluated on
every update and from the request's own send time, so a card that was detached and attached again
cannot keep a request pending for ever.

If nothing answers for 30 s the card shows **No result yet. Check Last action before trying again;
do not press Save twice.** It does not resend. If Home Assistant rejects the call the card says it
may not have reached the dongle. In both cases **the confirmation does not come back**: every
attempt uses the arm up (the dongle turns it off, even when it refuses), so the card shows the arm
as a strip ("This arm was already used by your request") with *Turn arm off*, and Save is refused
until you turn the arm off, press *Arm Save* again (a new arm episode, a new `switch.turn_on`) and
confirm again. A *Review* press does not clear an unanswered request either; only the dongle's
answer does, and the dongle's one-shot arm and candidate decide whatever is sent.

#### Invalidate

Only for a VALID profile (a lagging witness is fine), and only with an arm entity. In the Saved
profile card: *Arm Invalidate*, then a confirmation panel that names the stored profile's **full
16-hex binding** (the `id` of the summary, not the 8-digit short ID), the generation, the phrase
`INVALIDATE <binding>` and the prerequisites: no operation in flight, a free bus, a generation that
can advance, and the saved values agreeing with the record ID. It does **not** need a stable
heartbeat, trusted time, clear obligations or the other arms. If a candidate exists the panel says
that invalidating also discards it. *Invalidate Profile* sends one request, like Save. An invalidate
is a single synchronous step in the dongle: the outcome (`INVALIDATED`, `INVALIDATE REFUSED`,
`INVALIDATE NOT COMMITTED`, `INVALIDATE OUTCOME UNKNOWN`) appears in the Saved profile card. The
saved values are kept for reference; the profile is never used again until a new save.

One arm serves both actions, so the card remembers which one you armed for and who switched it on
(in memory only, never stored): the Save panel is hidden while the arm is set for Invalidate and
the other way round, and **neither panel opens for an arm this card did not switch on for it**.
An arm that is on without an Arm click of this card (another tab or user, the Home Assistant UI,
or after a reload) shows a strip - "Arm was turned on elsewhere" - with a *Turn arm off* button
instead, for every action; a Save or Invalidate that is somehow requested for it is refused. The
strip also says when the arm is set for Invalidate, when it is on with no candidate to confirm,
and when a request of this card has already used it up.

#### What the card guarantees, and what the dongle enforces

The card's own gates only avoid wasting a one-shot arm and candidate: the **safety authority is the
dongle**. It refuses unless all of these hold, whatever the card sends: the arm is on; the ID is the
current candidate's (or the stored profile's) and is 16 upper-case hex digits; the confirmation
phrase is exactly `SAVE <ID>` (plus ` REPLACE CORRUPT` only for a damaged prior) or
`INVALIDATE <ID>`; the candidate is younger than 120 s; the Home Assistant heartbeat is stable;
the clock is trusted; no other write arm is on; the bus is idle; no temporary operation is active.
Every execute call turns the arm off and uses up the candidate, accepted or refused (one-shot).

What the card adds on top, and pins in tests:

- **The five guarded actions need a trusted click.** *Arm Save*, *Arm Invalidate*, *Cancel* /
  *Turn arm off*, *Save* and *Invalidate* do nothing for an event that a script dispatched
  (`event.isTrusted` false). Keyboard activation of a button is trusted. **Review and the
  technical-detail toggle do not need one**: a script-made click still presses Review (a
  read-only review) or toggles the detail view. The trust decision is made inside the click
  listener's closure, which hands a module-private pass to the handler for a trusted event only; no
  argument of a public method (not `_act`, not `_onClick`) can carry it, so another script cannot
  call the card's methods with a "trusted" flag. This stops script-made clicks and nothing more:
  a script with access to the page can still call `hass.callService` itself, so it is defence in
  depth, not the safety authority.
- **No call from a timer, a render, a state change or a transition.** The five guarded actions
  (`arm`, `arm-invalidate`, `arm-cancel`, `save`, `invalidate`) are the only code that builds an arm
  or execute call, and each goes through one guard function.
- **The ID that goes out is the one on screen.** The Save button carries the ID it was drawn with;
  the handler compares it with the current ID before sending.
- **Never an automatic retry**, and no second request while one is pending.
- **No automation or script turns the arm on or calls the action.** No Home Assistant file but the
  dashboard card config names the arm switch or the action (a repository test pins it).
- **Restore stays absent.** No restore, acknowledge or write to the inverter exists in the card.

### Safety audit follow-ups (card-fix)

An independent safety audit of the FB-B2 card (CARD-01 to CARD-14) led to these changes; each has a
test that fails without it:

- **Heartbeat (CARD-01).** A supervision state that is shown and is not SUPERVISED fails the prerequisite
  and check 5 whatever the stable entity says (see Save readiness).
- **Escaping (CARD-02).** Every gate reason (it can carry entity text such as the supervision state) reaches
  the markup only through the escaping helpers `titleAttr`, `noteDiv` and `withRem`.
- **Missing tests (CARD-03).** An unknown time left, the REPLACE CORRUPT variant following the candidate's
  prior (never B1), the exact unknown-outcome guidance, a scan that no text claims a save or an invalidate as
  done outside a verified outcome, and the arm timer re-anchoring are pinned.
- **No double submit (CARD-04, 05, 06).** An attempt uses the arm up; the confirmation never comes back after
  a timeout or a rejected call; Review does not clear an unanswered request; the arm turning off is not an
  answer by itself; the 30 s limit survives a detach / attach.
- **Values on screen (CARD-07).** Save needs the candidate values and the saved-profile summary; no
  generation is derived from missing data.
- **Whose arm (CARD-08).** The confirmation opens only for the arm this card switched on for that action.
- **Trusted click (CARD-09).** The trust decision lives in the click listener's closure; the claim is worded as
  the code does it (Review and the detail toggle are not guarded).
- **One id per key (CARD-10).** The configuration is refused when an id is used twice.
- **Verified (CARD-11).** "Saved and verified" also needs `w=OK`, `werr=-` and the matching `op`.
- **Focus (CARD-12).** The outcome takes the keyboard focus from the progress row.
- **Tests that cannot hang (CARD-14).** Every card a test creates is disconnected after it, pass or fail.

Not changed here: **CARD-13**, the comment of `deployment/ha-manifest.yaml` still describes the card as the
FB-B1 read-only review. The manifest is a pinned artifact (changing it needs a scope-chain entry reverter), so
it is an owner decision recorded here, not a card change.

### Live Match wording

The headline is about the **settings and the context** (the `dx` and `dc` masks). The sentence under it
never claims more than the firmware published:

| What the review published | Headline | Sentence |
|---|---|---|
| `dx`, `dc` and `di` all zero | MATCHES SAVED PROFILE | `31 of 31 registers matched at the review <age> ago.` |
| `dx` and `dc` zero, `di` not zero (only information-only registers differ) | MATCHES SAVED PROFILE | `All compared settings and context matched at the review <age> ago. Info-only values differ (not restored by Fallback V1).` |
| `dx` and `dc` zero, no `di` | MATCHES SAVED PROFILE | `All compared settings and context matched ... Info-only values were not compared.` |
| `dx` or `dc` not zero | DIFFERS or DIFFERS (CONTEXT) | the number of places and the chips, as before |
| the candidate was not compared (see below) | UNKNOWN | says why |

The literal "31 of 31" appears only in the first row.

### A stored profile the firmware does not trust

The firmware computes `dx`, `dc` and `di` only against a **trusted** stored profile: an authentic record whose
effective class is not `UNREADABLE`. Otherwise they are `-`, and the saved views (B7, B8) are `v=NONE`. The card
treats that as "not compared", never as "no differences":

- Live Match is UNKNOWN and says why (for `UNREADABLE`: "The stored profile could not be read, so it cannot be
  trusted and no match is reported."; a never-captured profile and an invalidated one keep "No saved profile to
  compare against.", and a lost one says it is missing from storage);
- the Summary card shows no difference marker and no legend, adds the line "Not compared: the stored profile is
  UNREADABLE and cannot be trusted, so no difference markers are shown.", and its disabled **Saved profile**
  button reads `not trusted` (tooltip: the profile is not trusted and no saved values are shown);
- the register table leaves every Δ cell at `—` and repeats the "Not compared" line in its caption.

The card applies this rule itself as well: an `UNREADABLE` class in B1 or in the candidate's prior class is never
comparable, even if masks were published next to it, so a marker or a "matches" claim cannot appear against a
profile the firmware calls unreadable.

### Eligibility ("Eligible to save")

A candidate is eligible only when **all four** hold: the firmware state is `CANDIDATE_READY`,
the value verdict is `sv=OK`, the stored profile's class permits a save (not `UNREADABLE` or
`SAVE_UNCONFIRMED`, and a class the card recognises), and the candidate has a real 16-digit ID.
Anything else reads `No`, with the reasons listed in the candidate card, and check 2 fails
whenever `sv` is not `OK` - also for a `READY` candidate. The firmware never produces such a
combination today; the rule is there so a later firmware or a corrupted entity cannot make the
card look green. Expiry is applied on top: at the last second the card says `No (expiring)`.
Eligible is necessary for a save, not sufficient: Arm Save needs every prerequisite of the
confirmation panel as well.

### The countdown

The firmware publishes the candidate's remaining seconds (`exp`) about every 10 seconds. The card
renders a smooth per-second countdown **derived** from that value and the time the entity last
changed. It is never an independent clock:

- every new publish re-anchors it (it snaps up or down);
- it is never rounded up, and shows `expiring…` (not `0:00`) at zero until the firmware itself
  confirms the expiry. While it waits, the candidate card says **Expiring - waiting for the
  firmware** in an amber row and footer; it never says "expired" on its own;
- the firmware applies the 120 s expiry on its own 10 s tick, so a candidate can stay published for up to about
  10 s after 120 s ("120 s plus up to one tick"); the card shows `expiring…` for that time;
- the timer only runs while a candidate or an armed switch is on screen and the tab is visible;
- a browser clock that differs from the Home Assistant server clock shifts the countdown by that
  difference until the next publish (the card clamps a publish time in the future to "now").

The **arm timer** works the same way: it counts 120 s from the moment Home Assistant last changed
the arm switch to on, shows `expiring…` at zero and offers no confirm from then on (the switch can
stay on for up to about 10 s longer, until the dongle's tick turns it off). It stops counting a
minute after the limit if the switch is still reported on.

**One rule for exactly 45 seconds.** More than 45 s left is plain (grey digits, check 3 passes).
45 s and below is amber with the caption `expiring soon`, and check 3 warns with the same
threshold; below 15 s the digits pulse. The countdown colour and check 3 share one function, so
they cannot disagree. (The design text is not consistent about 45 s itself; the card follows the
countdown table in design section 6.)

### Save readiness: what is live and what is not

Checks 1 to 4 come from the last review; checks 5 and 6 (supervision, trusted time) are live. Check 5
needs the supervision state **SUPERVISED and** a stable run of beats ("SUPERVISED alone is
insufficient"). A state that is shown and is not SUPERVISED is **not met whatever the stable entity says**
(it may be unavailable): "Supervision state is LOST, not SUPERVISED", in check 5, its footer, the
confirmation panel and the Arm Save tooltip alike. A stable flag with no state entity, or a missing
stable entity with the state SUPERVISED, is unknown (the dongle checks it when you save). The footer of card 5 also counts what the six checks do not cover (another write
arm, the bus, an operation that is not clear) and ends with "Save is allowed once the arm is on" or
"Save is armed: confirm it in the candidate card". "Armed" is said only for an arm this card switched
on for a save; an arm that is on for anything else (another tab, a reload, an Invalidate, a request that
already used it) gets its own warning sentence there, because the candidate card shows no confirmation.

Check 4, "No temporary operation active", is read from the obligation vector (`obl`) that the
Review gate publishes. The firmware **keeps publishing that vector unchanged** after the review
ends, after the candidate expires and after a clearing event, so a stale "all clear" must not be
presented as the current state. The card therefore judges the vector only while it is the gate's
current outcome:

| State | Check 4 |
|---|---|
| a candidate exists, or a read is in progress | pass `... clear at Review`, or warning / not met from the vector |
| the last review was refused | the refusal's own verdict (not met, with the domain named) |
| expired, read not completed, mismatch, internal reset, or idle after a review | **unknown**, `Last checked at Review (not live)` (the old vector is in the tooltip) |
| cleared (`REVIEW CLEARED`) | **warning**, with the clearing reason from the last-action text |
| never reviewed (`obl=-`) | unknown, `Checked at Review` |

A vector that is not exactly six entries `FP,DP,R4,MT,FS,BUS` in that order is not judged at all
(unknown, "not recognised"); it is never read as clear.

### Pass columns in the raw table

The firmware publishes one set of register words, and only when both read passes agreed. The raw
table therefore never invents per-pass data: with a candidate both pass columns show the one
published word; after a pass mismatch only the register the firmware names has values; in every
other state the pass columns are empty.

### Technical detail

The "Show technical detail" toggle is remembered **per browser** in `localStorage` (every access
is guarded; a browser that blocks storage still works). If you configure
`technical_detail_entity` (an `input_boolean`) and it reports `on` / `off`, the card follows that
helper instead and toggles it with `input_boolean.toggle`; the state is then shared across
browsers. No helper is created by this card.

While the detail is open the firmware re-publishes the review string about every 10 seconds. Card 7
is **patched in place** instead of being rebuilt: the register table keeps its scroll position,
keyboard focus stays on its scroll region, and a text selection survives (only the characters that
changed are rewritten, so selecting a whole raw string and watching its countdown digits tick does
not lose the selection).

### Service calls

The card can make exactly these service calls, and enforces that in code (an allow-list that every
call passes through before `hass.callService`):

1. `button.press` on `entities.review_button`;
2. `input_boolean.toggle` on `technical_detail_entity` (only when configured);
3. `switch.turn_on` and `switch.turn_off` on `entities.arm` (only when configured, only when that id
   is not also another configured entity; only from a trusted click);
4. `esphome.ecco_clock_dongle_fallback_profile_execute` with exactly the keys `action`
   (`SAVE` or `INVALIDATE`), `target_id` (16 upper-case hex digits) and `confirmation` (the phrase
   built from those two values); only from a trusted click and only with `entities.arm` configured.

The service name is `esphome.<node name>_<api action>`: the ESPHome node of the dongle is
`ecco-clock-dongle` and its API action is `fallback_profile_execute`. A repository test derives the
name from the firmware and compares it with the card's constant.

It reads exactly five members of Home Assistant's `hass` object (`states`, `locale`, `config`,
`language`, `callService`) and dispatches one event (`hass-more-info`, to open an entity's detail
dialog). There is no WebSocket call, REST call, message or action event anywhere in the source; the
repository test fails if one appears.

### Accessibility

State is conveyed by a word, a colour and an icon. The review headline and the last-action line
are polite live regions that keep their element between renders; the countdown is not announced,
except one announcement when 15 seconds remain. Disabled controls stay focusable (`aria-disabled`,
never the `disabled` attribute) and explain why in a tooltip and a visible caption. Focus rings are
visible. The Review button, the Candidate / Saved selector, the technical-detail toggle and every
Save / Invalidate button are at least 44 px high for every pointer. `prefers-reduced-motion` turns
off every animation and transition (the stepper pulse, the countdown pulse, the rail and skeleton
shimmer, the bar transition, the save spinner) and smooth scrolling. The register tables scroll
inside their own focusable region on narrow cards.

The confirmation panels are named groups (`role="group"`, `aria-labelledby` the panel heading). When
the panel opens after an Arm click, focus moves to its heading, **not** to the Save button; Cancel
returns focus to the button that started the flow; a re-render that replaces the panel's markup keeps
focus on the same control by its focus key. The request in progress is a `role="status"` region with
`aria-busy`; the outcome is announced through the last-action line, which is already a polite live
region. When the progress row that holds the keyboard focus is replaced by the outcome (or by the
"no result yet" message), **focus moves to the result heading** (the candidate card's headline, or the
result block of the Saved profile card for an invalidate) instead of falling to the page; focus is
never moved there if you had already moved it elsewhere, and never to a button. Clicks on the text of a confirmation panel or a result block do nothing (they never open the
card's more-info dialog).

Two notes for keyboard and screen-reader users:

- **Tab order on a phone.** When the card is narrower than 700 px the Review card is moved to the
  top with CSS (`order`), as the design asks. Tab order and reading order stay in document order:
  Saved profile, Live match, then Review. Reordering the markup would change the order on wide
  layouts as well, so it is documented instead: on a phone the Review button is a few tab stops in
  (the `details` pill in card 1 and the `values` pill in card 2 come first).
- **Whole-card taps are pointer shortcuts.** Tapping card 1 opens the profile entity's detail
  dialog and tapping card 2 scrolls to the summary. Keyboard and screen-reader users get the same
  actions from the `details` and `values` pills in those cards.

### Responsive layout

The layout reacts to the **card's own width** (container queries), not the viewport: four columns
above 1100 px, two up to 700 px (Candidate and Save readiness side by side), one below, where the
Review card moves to the top. Below 420 px the slot table folds its Mode column under Source and a
difference marker inside a table cell or tile stacks its old value underneath (the marker in the
"Not restored by Fallback V1" sentence stays inline). The confirmation panel lists its prerequisites
in two columns when its card is 560 px wide or more, and one column below; its long phrase and
generation text wrap instead of scrolling.

## Deviations from the mockup

The mockup is the visual contract: colours, type scale, radius, chips, stepper, ghosts and the
card anatomy are identical (the computed styles match at 1280 px). The differences below are
deliberate; nothing else was changed.

**Behaviour that the mockup shows differently**

- **Check 4 is not live outside a review.** The mockup's `cleared` scenario used a vector the
  firmware never produces (`DP:ST` first) and its idle states showed a green check 4 from any vector.
  See "Save readiness" above. Reason: the firmware keeps the last vector after the review.
- **The 45 s rule.** Mockup check 3 passes at exactly 45 s while its countdown is amber at 45 s.
  The card uses one rule for both (amber at 45 s and below). Reason: design section 6.
- **At zero the card does not say "expired".** The mockup adds a red `Candidate expired.` row while the
  headline is still `CANDIDATE READY`. The card shows `Expiring - waiting for the firmware` (amber), keeps
  Eligible at `No (expiring)` and leaves the verdict to the firmware. Reason: design section 6, "do not
  declare expiry".
- **Eligibility** is the four-part rule above (the mockup only looked at the blocker list), and
  blockers are listed for a `READY` candidate too.
- **Live Match counts every difference.** The mockup's `DIFFERS (CONTEXT)` sentence counts only the
  context bits; the card counts context and settings together, so the number matches the chips. The
  headline is unchanged.
- **Live Match does not say "31 of 31" while information-only registers differ.** The design words the
  matching state as "31 of 31 registers matched ..." and, when only information-only registers differ
  (230, 245, 247, or the upper bits of 232 and 248), appends "Info-only values differ." The two halves
  contradict each other: two registers visibly differ, so not all 31 matched. The headline stays
  `MATCHES SAVED PROFILE` (settings and context are equal), and the sentence becomes "All compared
  settings and context matched at the review <age> ago. Info-only values differ (not restored by
  Fallback V1)." The design's "31 of 31 registers matched at the review <age> ago." is kept for the case
  where `di` is zero. Reason: the sentence must not claim more than the firmware published.
- **A stored profile the firmware does not trust is not "compared".** The design has no state for an
  authentic record whose effective class is `UNREADABLE` (the firmware prints `dx`, `dc` and `di` as `-`
  and the saved views as `v=NONE` there). The card says so in Live Match, in the Summary card (no
  markers, a "Not compared" line, a `not trusted` saved-source button) and in the register table.
  See "A stored profile the firmware does not trust" above.
- **Candidate "Created" time** is the moment the firmware built the candidate (publish time minus the
  seconds already used), not the moment the page received the value.
- **Unavailable inputs** are never green: an unavailable supervision or NTP entity is an unknown row
  and a grey badge. Prototype-looking text from an entity (`constructor`, `__proto__`) is shown as
  text, never as a lookup into a built-in object.
- **The Save placeholder is real, and the arm tile is gone (FB-B2).** The design's disabled
  `Save Fallback Profile` button with a `Coming in FB-B2` chip is replaced by the guarded flow, in the
  same footer position; the design's `Suspend / Arm` ghost tile in the Recovery area is removed
  because the arm is a live control in the Candidate and Saved profile cards (three ghost tiles
  remain). The design asks every future write control to carry a Home Assistant `confirmation:`
  block; a custom card cannot use that block, so the card supplies its own confirmation panel (see
  above). The button label stays `Save Fallback Profile` (the specification's `Save Known-Good
  Profile` was not chosen) and the candidate row is `Eligible to save`.
- **REPLACE CORRUPT is verified by `op=RC`.** The FB-B2 brief says the saved-and-verified wording needs
  `op=SAVE`; the dongle publishes `op=RC` after a REPLACE CORRUPT save (and `op=SAVE` after a plain one), so
  the card accepts either for a save. Anything else (`INV`, `-`) is not verified.
- **The arm turning off answers a request only after 5 s.** The brief says to keep a request pending until
  B3 leaves CANDIDATE_READY or B9 changes; the card adds one more way out, the arm staying off for 5 s with
  nothing else published, because a repeated identical outcome (for example the same invalidate refusal
  twice) changes no entity at all and the request would otherwise wait for the 30 s message.
- **Where Invalidate lives.** The Saved profile card carries it (arm, confirmation panel, outcome).
  A confirmation panel is a tall block inside a one-column card on a wide screen; the cards in its row
  stretch with it while it is open.

**Layout and size**

- **One custom element with its own responsive grid.** The design lays the tab out as eight separate
  Home Assistant cards with per-card section spans (1, 1, 2, 2, 2, 4, 4, 4 columns of a four-column
  section) and a second, separately hidden copy of a card for the phone order. This is **one**
  `custom:ecco-fallback-recovery-card` element that fills a full-row section (`grid_options: columns: 48`)
  and lays the eight cards out itself: the spans became a CSS grid (four columns, two, one by the card's
  own width) and the per-card visibility copies became CSS `order` (see "Phone tab order" below).
  Reason: the cards read one derived state and one clock (the countdown, the selected source, the
  pending press); inside one element they share them directly, where separate cards would need helper
  entities and this card creates none. Consequence: the section spans of the design do not exist in the
  dashboard YAML, and the dashboard cannot hide or move one card independently of the others.
- **Slot table rows are 30 px**, like the mockup. The mockup page has no doctype, so its tables ignore
  the inherited line height (1.45) and use the font's own; the card fixes the table line height at 1.2,
  which gives the same 30 px rows with any font stack. The Review button is 46.3 px as in the mockup
  (buttons inherit the line height, as the mockup's `font: inherit` buttons do).
- **Candidate and Save readiness sit side by side at 820 px** (design section 2.2). The mockup stacks
  them.
- **Breakpoints follow the card's width, not the viewport** (`@container` at 1100 / 700 / 620 / 420 px
  instead of viewport media queries). Reason: in Home Assistant the card lives in a sections column,
  narrower than the screen; a 1280 px screen with the sidebar open gets the two-column layout.
- **The segmented source selector and the technical-detail toggle are 44 px high for every pointer**
  (the mockup uses 32 px; the touch-target rule is design section 9). The two header rows of cards 6 and
  7 are therefore taller than in the mockup.
- **Disabled segment opacity is .4**, as for the disabled buttons.
- **Card 1 states the storage condition in words** (`record read`, `integrity check mismatch`,
  `witness: valid`) instead of the mockup's raw codes, as design section 5.1 asks. For an unusable
  profile that is three short lines instead of one (about 50 px taller).
- **The reason a disabled Review button is disabled is its own amber line** under the caption, not text
  appended to the caption (about 11 px taller while a review is reading).
- **A `details` pill in card 1 and a `values` pill in card 2** (about 10 px of extra height). They are
  the keyboard path to the whole-card tap actions, which neither the spec nor the mockup have.
- **The two scroll regions (slot table and register table) carry focus keys**, so keyboard focus comes
  back to them after a rebuild; the obligation-vector block in card 7 is titled "as of the last review".
- **Phone tab order follows the markup**, as in the mockup: the Review card is moved to the top with CSS
  only (see Accessibility).

**Known and kept**

- **The phone fold target is not met.** The design wants the status row above the fold on a phone, each
  card at most 160 px tall. On a 390 px phone each status card is 216 to 394 px tall (a few pixels either
  way with the font): on an 844 px screen the Review card, moved to the top, and Saved profile fit, and
  Live match starts at about 780 px and is cut off by the fold. The mockup misses the target in the same
  way. Fixing it needs a content change (shorter sentences), not a layout change, so it is kept for the
  owner to decide whether the 160 px target stays.

## Development

```powershell
cd frontend\ecco-fallback-recovery-card
npm test                      # node --test test/*.test.mjs  (no dependencies to install)
python -m http.server 8765    # then open http://localhost:8765/preview/#ready_diff
```

`preview/index.html` runs the real card against a mock `hass` object and the scenarios in
`test/fixtures/scenarios.json`. Choose a scenario from the panel, with `#<scenario>` or with
`?scenario=<scenario>` (add `chrome=0` to hide the panels). The preview rejects and logs every
service call except the Review press, the arm switch on its configured id, the execute action with
well-formed keys and the optional detail toggle. A small stand-in for the dongle answers them (a
review, the arm with its 120 s limit, SAVE and INVALIDATE with the firmware's gate order); the
option panel picks what an accepted save or invalidate ends with, so every result state can be
looked at. It must be served over HTTP; browsers refuse ES module imports from `file://` pages.
A real click on the card is a trusted event; a click that a script dispatches (for example
`button.click()` from the console) is ignored by the five guarded actions (Arm Save, Arm Invalidate,
Cancel, Save, Invalidate) by design, while Review and the technical-detail toggle still work for it.
The preview's "Slow link" option delivers the arm turning off 2.5 s before the review state and the
last action, to look at a request that stays pending until the dongle really answers; the scenarios
that start with `arm_on_` start with the arm already on (as if set elsewhere): they show the strip,
never a confirmation panel.

`test/fixtures/scenarios.json` maps a scenario name to the state string of each configured entity
key (`{ "ready_diff": { "profile_state": "VALID", "summary": "g=7;...", ... } }`), so the same file
can be regenerated from the firmware's own text builders and the tests re-run against it.
`test/fixtures/scenario_meta.json` holds the expected derived view of each scenario. Every scenario
carries the four arm keys (`arm`, `free_power_arm`, `dump_arm`, `manual_arm`).

Tests (all plain `node --test`, no dependencies):

| File | What it covers |
|---|---|
| `test/core.test.mjs` | parsers, decoders, masks, state derivation, countdown, register table, the six checks, eligibility; the save and invalidate gates (every prerequisite failing alone), the service-call builders and the allow-list negatives, the request state machine, the B9 families |
| `test/render.test.mjs` | every scenario renders, wording hygiene (also for every Save / Invalidate state), escaping, CSS rules (motion, narrow layout, touch targets), the confirmation panels, outcome panels, accessibility structure, the source guards |
| `test/element.test.mjs` | the custom element against a strict mock `hass` that throws on any member the card may not use: clicks delivered through the registered click listener (the only holder of the trusted pass), one call per click, pending, timeout and detach / attach, no retry, a stale ID, whose arm it is, a closing confirmation, timers; every card a test creates is disconnected afterwards |
| `test/dom.test.mjs` | the same element on **real node trees** (`test/minidom.mjs`): in-place patching of card 7, scroll position, selection, focus (including the hand-over of the focus from the progress row to the outcome), a click on the real button, and that every card equals a fresh render after any scenario-to-scenario transition (card 7 on every pair in both detail states) |

`test/dump-strings.mjs`, `test/check-b9.mjs` and `test/check-obl.mjs` are not tests: the repository check runs
them to scan every string the card can print, to feed it every B9 text and every obligation vector the
firmware mirrors can produce (the review texts and the Save / Invalidate texts), and to confirm the
card accepts them.

Repository checks for this card (placement of the dashboard view and the pin that it is the only change
to the dashboard file, entity-id derivation, service call hygiene, wording hygiene, register order, the
firmware-mirror cross-checks, the execute service name against the firmware, that nothing else in
`home-assistant/` can act on the arm, this README) live in
`registry/tests/test_fallback_recovery_dashboard.py`, which also runs the node tests. That makes **Node
(version 20 or newer) a requirement of the repository check**: the check fails with a clear message when
`node` is not on the path.

## License

GPL-3.0-or-later, the licence of the ECCO-Pro project (see the repository's `LICENSE` file). The card has no
third-party runtime dependency; its inline icons are simple shapes drawn for this card.
