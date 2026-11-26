# Energy Plan UI: UX concept (phase 1, offline design)

**Status: DESIGN ONLY.** This is a concept and an offline mock (`mock/index.html`, fictional data, no network). Nothing here is
implemented in Home Assistant, the firmware or any card, and nothing here authorises a change. The evidence for what is and is
not possible today is in [FEASIBILITY_MATRIX.md](FEASIBILITY_MATRIX.md); the order of work is in [ROADMAP.md](ROADMAP.md).

## 1. Principles

1. **Two everyday authoring surfaces.** *Charge Battery* (today's Free Power) and *Export to Grid* (today's Dump to Grid)
   are the only places where an owner makes energy plans. The TOU schedule is shown, not edited, in daily use.
2. **One canonical plan.** Every setting exists once. Every surface that shows it binds to that one field; there are no
   copies that can drift.
3. **Draft, saved and actual are different things, and look different.** An edit is a draft preview. A saved plan is the
   owner's intent. Only verified inverter readback is "actual". A dashboard edit never claims to have changed hardware.
4. **Gentle by default.** The overnight charge default is the lowest steady rate that still finishes a chosen number of
   minutes before the cheap window ends, not the maximum rate.
5. **Honest feasibility.** When a goal cannot be met inside the proven limits, the plan says what will happen instead (for
   example "reaches about 62 %, not 10 %, by 21:00") and keeps every protection.
6. **Every write keeps today's gates.** Read, review, typed confirmation, apply, verified readback, and undo where it exists.
   No new raw-write route. The 10 % export floor is never offered lower.
7. **Labels tell the truth.** In the mock every widget carries one tag: *Works today* (an existing feature with fictional
   values), *Proposal* (not a working feature), *Derived* (read-only view) or *Simulation* (fake backend for test cases).
8. **Few decisions.** Hysteresis and linked settings keep repeated owner decisions rare; profiles change several preferences
   in one reviewed step.
9. **Calm, plain English, phone first, accessible.** No register numbers or entity ids in the daily views.

## 2. Views

| View | Purpose | Main content |
|---|---|---|
| **Home** | the calm everyday overview | battery, solar, house, grid and price; tonight's plan in one sentence and a linked-cycle strip; the existing energy-flow card in its usual place (unchanged; the mock shows a placeholder and no house artwork); the Intelligence summary; one status indicator in the header |
| **Controls** | make and see plans | the profile switch (Normal / Summer Solar Priority); the two master cards side by side (stacked on a phone); the derived 24-hour TOU timeline with the plan drawn on top |
| **Intelligence** | what is predicted, recommended and applied, as three separate columns | forecasts with uncertainty; advice with reasons and confidence; withheld items explained in plain words; "Applied: nothing" while in SHADOW; a *Suggested plan* in the same form as the owner's, which can be adopted as a draft |
| **Advanced** | technicians and diagnostics | Manual TOU (native, through the existing guarded editor); the compiler's output; who owns each setting; the scenario lab and the cross-card checks; raw registers, recovery and proofs (existing cards, moved out of the daily views) |

The single status indicator reads, in order of priority: *Inverter changed outside the plan* (drift), *Planning paused*
(stale readings, Home Assistant offline, unreadable table), *Plan needs a look* (a refusal or a shortfall), *All good*.

## 3. The two master cards

Both cards keep today's working behaviour underneath. The new names are presentation only; entity ids and firmware feature
names do not change until a separately reviewed compatibility migration.

| | Charge Battery | Export to Grid |
|---|---|---|
| Subtitle | Grid charging and smart schedules | Export stored energy when permitted ("Export" rather than "Sell": exporting is not always paid) |
| **Now** | today's Free Power NOW (*Works today*) | today's Dump to Grid NOW (*Works today*) |
| **Schedule** | today's Scheduled Free Power (*Works today*) | today's Scheduled Dump to Grid (*Works today*, but not live-proven yet) |
| **Smart Target** | *Gentle Overnight* settings (mode, target, finish-before-end buffer 0-120 min, maximum power) and *Smart Charge (daytime goal)*; collapsed *Advanced dynamic settings* that are simulation only (*Proposal*) | *Smart Export* (export down to, finish before the next charge window or at a time, handover gap) and collapsed *Make room for predicted solar (Summer)* (*Proposal*) |
| Always visible | Planned / armed / running / stopped / restored, and any recovery state, even when the card is on another tab | the same |

Charge modes are **ECCO planning preferences**, not inverter registers: *Gentle* (default), *Standard / native*, and
greyed-out *Lowest Cost* (needs verified rates) and *Intelligence suggested* (review first).

## 4. The canonical plan

### 4.1 Shape

```
plan (revision n)
  profile           normal | summer
  charge            strategy, targetSoc, bufferMin, maxChargeW, stepped, day{targetSoc, byTime}
  export            enabled, stopSoc, finishMode (before_charge | at_time), gapMin, finishAt
  summer            enabled, minReserveSoc, confidenceMin, maxPreSolarKwh, gapBeforePvMin
saved               { revision, plan, basisTou }   basisTou = the slot readback the plan was saved against
draft               { revision n+1, plan }         browser-side until saved; never sent anywhere
readback            the six slots as last read from the inverter (facts)
```

### 4.2 Precedence

Highest first: **safety stop and restore** > **an active firmware transaction or its recovery** > **an owner's manual action
or a paused plan** > **the confirmed plan** > **advisory optimisation**. An inverter fact (readback) always wins over a plan
value for what is physically true; the plan is the owner's intent for what should be true.

### 4.3 Scopes (designed, not yet in the mock)

- **Global default** (what the mock implements).
- **Per charge-window override**, keyed by a stable window identity (the run of grid-charge slots and its start), so that a
  restructured table resolves or blocks an orphaned override instead of applying it to the wrong period.
- **One-off session override**, which expires with its session.

Each shows its source and the effective value.

### 4.4 Who owns each setting

| Setting | Canonical owner | Live readback | How it changes | Gate |
|---|---|---|---|---|
| Slot start, power, target SOC, charge source | inverter (fact) | the slot readback | the existing guarded editor, one setting of one slot | Review, typed confirmation, Apply, readback; midnight-crossing hold; clock-change nights; refused during sessions |
| Charge target | owner's plan | the grid-charge slot's target SOC | a proposed slot edit, owner-reviewed | as above |
| Finish-before-end buffer, charge mode, maximum charge power | owner's plan (ECCO only) | none: no inverter register | a plan helper (proposal) | draft, review, save |
| Export Stop SOC, finish mode, handover gap | owner's plan | Dump Stop SOC at START | the existing scheduled Dump fields; the owner arms | firmware 10-90 %, charge-slot overlap check, export headroom, snapshot and restore |
| Dump power ceiling, maximum grid export | protected operating limits | firmware | separate arm, idle only (unchanged) | not editable from the everyday cards |
| Intelligence planning reserve | Intelligence settings (advice) | n/a | Intelligence configuration | never a hard floor |
| Now / Schedule values | existing helpers and request numbers | the dongle numbers | the existing cards, unchanged | existing gates; SMR1 restores the owner's manual values after a scheduled start |

## 5. Derivations (what every card shows from the same plan)

- **Charge window** = the run of consecutive slots whose charge source is Grid, as read back; it may cross midnight. If the
  window is already running, planning starts from now with the minutes left.
- **Finish-by** = window end - buffer.
- **Expected start SOC** = the export's end SOC (if an export is planned) or the current SOC, minus the house's overnight use
  until the window opens.
- **Gentle rate** = the lowest steady rate, in 100 W steps and at least 500 W, that adds the needed energy by the finish-by
  time, using the larger of the configured and learned capacities. It is capped by the smallest of the owner's maximum,
  the inverter, the battery's configured charge current, the grid-charge current setting and the maximum grid-charge
  power. If a cap binds, every surface (card, cycle strip, Home summary) shows the SOC or the finish time it will reach
  instead.
- **Export floor** = the greater of 10 % and the inverter's battery shutdown level; no plan if the shutdown level cannot
  be read; a warning (not a refusal) below the Home Assistant reserve setting.
- **Export finish-by** = next grid-charge start - handover gap (or a fixed time, which must be before the next charge
  window opens).
- **Export start** = now (plus a few minutes to stage), or later if the 240-minute session limit requires it.
- **Net export rate** = (battery energy above the target x discharge efficiency / time available) - house load, rounded up to
  100 W, at least 500 W, never above the allowed net export (the maximum export minus its margin, and the hardware-tested
  battery ceiling minus the house load). Net export is what the firmware tracks; battery discharge is shown separately.
- **Worth it?** = export revenue - the cost of replacing the exported energy at the cheap rate after losses - cycle wear
  (fictional prices in the mock). Only the exported energy counts; the house would have used its share anyway.
- **Summer pre-solar export** = the smallest of: the conservative surplus after the house minus the battery's free room; the
  owner's per-event cap; the energy above the owner's floor (never below 10 %); what the hardware-tested rate can export
  before the learned solar onset minus a gap. Below the confidence threshold, or when it would not pay after losses and
  wear, the answer is "hold".

## 6. The compiler and the single writer

The compiler is a pure function from (plan, readback, context) to **actions**, **refusals**, **notes** and a
**compensation** list. The mock implements it in `PlanModel.compile`.

- Native slot changes only when needed, and only within the grid-charge run; never an unrelated slot.
- Gentle overnight compiles to at most one power edit and one target edit per charge slot, each a separate guarded edit at
  least 5 minutes apart; a rate difference under 500 W is ignored (hysteresis).
- An export compiles to one scheduled Dump session (the existing fields; the owner arms it).
- Refused, with the reason: more than six slots needed (for example a stepped profile), an export that overlaps a
  grid-charge slot (its end minute counts), an export that would finish after the next charge window opens, an export
  floor that cannot be confirmed, a handover gap under 10 minutes, an export over 00:00-03:00 on a clock-change night, no grid-charge
  window, an unreadable table, stale readings, drift since the plan was saved.
- Deferred: every action while a session is active (one writer at a time); slot edits on a clock-change night. A
  simulated Apply sends nothing while anything is paused, blocked or deferred.
- Not atomic: a failed later edit leaves the earlier ones. The plan shows *Partial*, locks further edits and offers the
  compensation edits, each again a guarded edit; nothing is retried or reversed automatically.

## 7. Plan review

A draft opens a review sheet with three parts:

1. **What you changed**: field by field.
2. **What follows from it**: for example, for a longer handover gap, *Export ends 22:52 -> 22:25* and *Export rate (net)
   1,300 W -> 1,600 W*.
3. **What the inverter would be asked to do**: the compiled actions with their gate and status, the refusals, the change
   count and the compensation list.

Buttons: *Save plan*, *Discard draft*, and *Apply to inverter*, which in the mock is disabled and labelled as not a working
feature.

## 8. Reconciliation

| Event | Behaviour |
|---|---|
| External or manual change to the inverter | shown as **drift**; drafts and proposals blocked until the owner reviews; never silently overwritten |
| Backend refuses an edit | nothing written; the draft is discarded; every view shows the saved plan |
| Partial multi-edit | *Partial* shown with what was applied and what failed; locked; compensation offered |
| Home Assistant restart / reconnect | the saved plan and a fresh readback load; unsaved drafts (browser only) are dropped; nothing is re-sent |
| Stale readings, HA offline, unreadable table | planning paused; the inverter keeps running its own table |
| Clock-change night | slot edits deferred; no export over 00:00-03:00 |
| Profile switch | a reviewed draft that changes linked preferences only; never an action |

## 9. Acceptance tests built into the mock

`PlanModel.runChecks()` (run in the page under Advanced, and under Node by `mock/test/plan-model.test.mjs`):

| Id | The owner's test case |
|---|---|
| C1 | a TOU charge-start change re-derives the linked export finish (and is flagged as drift) |
| C2 | the handover gap is one field: export, timeline and Home summary all move |
| C3 | a finish-buffer change is a preview only |
| C4 | a backend refusal reconciles every view to the saved plan |
| C5 | an external inverter edit invalidates the draft preview |
| C6 | restart / reconnect keeps the saved plan and re-sends nothing |
| C7 | clock-change night: slot edits deferred, an export over 00:00-03:00 refused |
| C8 | no grid-charge window: both cards say so, nothing is compiled |
| C9 | more than six slots needed: explicit refusal, nothing truncated |
| C10 | no accidental 5 % export target: refused, not clamped |
| C11 | single writer: during an active session every planned action waits |
| C12 | an export ending exactly at the charge-slot start is refused (the end minute counts) |
| C13 | the hardware-tested export limit is never exceeded; the shortfall is shown |
| C14 | gentle = the lowest steady rate that still finishes by the finish-by time |
| C15 | buffer bounds 0-120 min in 5-minute steps |
| C16 | an interrupted multi-edit is reported as partial, with a compensation edit |
| C17 | standard (native) mode compiles no rate edit; gentle does |
| C18 | unrelated slots are never touched |
| C19 | a profile switch changes preferences only |
| C20 | low forecast confidence holds the battery |
| C21 | an export that would finish after the next charge window is refused |
| C22 | the one-line summary never hides a shortfall |
| C23 | inside a running charge window the plan starts from now |
| C24 | the export floor is the greater of 10 % and the inverter shutdown level; unreadable means no plan |

## 10. Mobile and accessibility

Single column on narrow screens and two columns where there is room (from about 730 px); a bottom navigation bar below
900 px and top navigation above. Every control is a native element with a label;
segmented controls are button groups with `aria-pressed`; the status is a polite live region; the review is a modal dialog
that closes with Escape; each timeline slot is a button with a full spoken description; nothing relies on colour alone;
light and dark schemes follow the system; motion respects `prefers-reduced-motion`.

## 11. Out of scope for this phase

- **A private house scene as a selectable energy-flow view.** It needs an owner review of the exact asset set and explicit
  confirmation before any public distribution, plus a tested migration and rollback plan for the protected live dashboard.
  Nothing from it is in this branch.
- Any live install, entity, helper or firmware change.
