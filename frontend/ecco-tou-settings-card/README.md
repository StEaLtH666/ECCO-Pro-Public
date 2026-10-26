# ECCO TOU Settings Card

A Home Assistant Lovelace card for the ECCO inverter's six **time-of-use (TOU) slots**: the live values of every slot, and a
**guarded editor** for the target SOC, the power and the charge source of one slot at a time, through the installed ECCO
Advanced Configuration Stage 1 editor (ACS1, `home-assistant/packages/ecco_tou_target_soc_edit.yaml`).

**Status.** Offline candidate (post-export entry `acu1`): built and tested locally, **not installed, not exercised in Home
Assistant, not live-proven**. It replaces the read-only TOU table in section 7 of the dashboard's Inverter / Advanced view
(dashboard 7.22.0, staged). The read-only Advanced / Experimental Configuration card (section 13) is unchanged.

## What the card can and cannot do

- **It can** ask the ACS1 editor to **Review** a change (writes nothing), **Apply** a reviewed change after you type its exact
  confirmation phrase, and **Acknowledge** an UNCERTAIN outcome after you type the acknowledgement phrase. These are the only
  three things it does to Home Assistant: three `script.turn_on` calls on
  `script.ecco_cfg_review_tou_slot_setting`, `script.ecco_cfg_apply_tou_slot_setting` and
  `script.ecco_cfg_acknowledge_edit_review`, with the variables those scripts define.
- **It cannot** write a register, press a dongle button, arm a write enable, stage a value, change a helper or call any other
  service. It holds **no safety logic of its own**: every gate (ownership by Free Power or Dump to Grid, the saved-profile and
  shadow states, the inverter's freshness, the clock-change nights, the value bounds, the quiet-bus Apply, the firmware
  readback, the two later reads and the gate counter) runs in the ACS1 scripts. What the card shows before a Review is
  **advisory**: it can only disable more than the scripts would refuse, never less, and the Review's refusal text is shown
  verbatim as the reason.
- **Success is reported only when the editor itself writes `APPLIED AND VERIFIED`.** A firmware readback alone, or any other
  signal, is never called success.
- **Start times are not editable here.** The reference site's slot layout wraps midnight, which the editor refuses as not
  strictly ascending (L1). The card shows that explanation and offers no route around it. Cyclic handling is a separate,
  reviewed development stream.
- **Provisional spacing (owner decision D5, 2026-10-25):** Apply is disabled for 300 s after the previous Apply the editor ran,
  whatever its outcome (`APPLIED AND VERIFIED`, `FAILED` or `UNCERTAIN`; the stamp is the editor's in-flight marker, which every Apply
  that passed its first gate sets and clears, so it survives the next Review; an Apply the editor REFUSED before its gate adds no
  stamp). This is a precaution the card enforces, not a firmware rule; it is not configurable in this version. The editor's own
  quiet-window gate stays authoritative.
- **Undo (owner decision D6):** after `APPLIED AND VERIFIED`, the card offers a new **Review** back to the previous value only when
  the result text and the owner-edit record agree on the slot, the setting and both values, a current live read shows the edited
  field at the post-edit value, and an edit of that slot is allowed right now (no advisory blocker). Otherwise no Undo is offered:
  review by hand.
- **A Review is tied to this card's proposal by slot, setting and value.** The confirm step binds to the live plan record and
  enables Apply only when that plan carries exactly the slot, setting and value reviewed in this card; the one-time code is read
  from the live record and typed by you. A plan for another value, made elsewhere (another browser, or this page before a reload),
  cannot be applied from here; it expires on its own after 10 minutes. A second browser's Review of the same value is accepted as
  the same edit. Apply is also held while any of the card's own advisory blockers is set (the editor would refuse it anyway).
- **Shadow latch (owner decision D3, not implementable as approved):** D3 approved reading the FB-C3 display decoders to show the
  latch up front, but the FB-C3 shadow-check UX suite under `home-assistant/tests/` (its check 15) pins that no file under
  `frontend/` names those decoders, and this card does not weaken a pinned check. The card therefore reads neither the dongle's
  saved-profile and shadow entities (reserved tokens) nor the decoders. When the Review refuses with "supervision not stable or a
  failback episode is open", the card shows that text verbatim and explains that a Home Assistant outage of more than about five
  minutes can latch the shadow and block every edit until a separately authorised, supervised dongle reboot. Amending the pin is a
  separate owner decision.

## The flow

1. **Table.** Six rows: window (the end is the next slot's start; slot 6 ends at slot 1's start), power (labelled Discharge limit or
   Export limit after register 244, as the dashboard does), target SOC, charge source, mode (read-only), freshness, and the slot
   that is active now. A pen opens the editor for power, target SOC or charge source; it is disabled, with the reason, whenever
   the status line shows a blocking condition, the editor's last result is not recognised, or the value is not editable (a live
   power that is not a multiple of 100 W, a generator charge source, missing SOC bounds, unreadable raw flags, values that are not
   current). **Freshness:** the dongle re-publishes a slot value only when it changes, so an unchanged value keeps the time it last
   changed; a value is *current* when its own report is at most 300 s old or when the configuration poll is current (online and
   read within 150 s, the editor's own limit). Each row's label says only what was checked: `live N; poll current`, `reported N; poll
   current` (or `poll not current`), `unchanged N; poll current`, `stale N; poll not current`, `timestamp unverified; ...` or `value
   unavailable; ...`. `max_age_configuration_s` only narrows when a row may say "live" (never beyond 300 s); it never widens what can be
   edited. The slot clock, the clock-change nights and the scheduled starts are read on the Europe/London clock, not the browser's. **The poll time itself** is the dongle's
   `YYYY-MM-DD HH:MM:SS` Europe/London wall time; the card parses it explicitly as Europe/London (so it reads the same in every
   browser zone and across GMT/BST), cross-checks it with the entity's own UTC `last_changed` (the larger age counts) and fails
   closed on an unparsable, impossible or future text ("Configuration read time unreadable", every pen off).
2. **Edit and Review.** Bounded inputs (power 500-8000 W in 100 W steps; target SOC from the greater of the inverter shutdown SOC
   and the ECCO reserve to 100 %; None / Grid). An effect line names the register, the change and every value rewritten
   unchanged. **Review** sends one `script.turn_on`; the card then waits for the editor's result text.
3. **Confirm and Apply.** The confirm panel shows the plan from the live record, its one-time code and the expiry countdown, and
   the exact phrase to type (`SET SLOT n TARGET SOC x REVIEW cccc`, `SET SLOT n POWER w W REVIEW cccc`, `SET SLOT n CHARGE
   SOURCE GRID|NONE REVIEW cccc`). The input is never pre-filled. **Apply** sends one `script.turn_on` with the typed phrase.
4. **Progress.** A derived strip (requested, staging loaded, armed, writing, firmware readback, judging), each step marked only
   when its signal has been seen. The editor publishes one `IN PROGRESS` text; the rest comes from its markers and the
   dongle's own last result.
5. **Outcome.** `APPLIED AND VERIFIED` (with Undo when allowed), `FAILED ... nothing written` and `REFUSED` verbatim, `UNCERTAIN` or
   the lock as a red banner with the recovery steps and the Acknowledge phrase. A result text the card does not recognise
   disables every control (fail closed).

## Configuration

```yaml
type: custom:ecco-tou-settings-card
title: Time of Use Schedule          # optional
entity_prefix: "ecco_clock_dongle"   # optional: your ECCO device slug
max_age_configuration_s: 300          # optional, 5-86400: display only ("live" vs "unchanged ...; poll current"); never widens editing
```

Unknown options are refused. Dongle entity ids are built at run time as `<domain>.<entity_prefix>_<object id>`; the editor's
helper ids (`input_text.ecco_cfg_*`, `input_boolean.ecco_cfg_*`, `script.ecco_cfg_*`) and `input_number.ecco_minimum_reserve_soc`
are fixed. `tools/ecco_site_render.py` renders the quoted slug in the example and the bundle for your site.

## Install (each step is the owner's, in order; nothing here deploys anything)

1. Build (or use the committed `dist/ecco-tou-settings-card.js`) and copy it with the project's deploy tool:
   ```powershell
   cls
   .\tools\deploy-ha.ps1 frontend\ecco-tou-settings-card\dist\ecco-tou-settings-card.js
   ```
   It lands at `/config/www/ecco/ecco-tou-settings-card.js` (served as `/local/ecco/ecco-tou-settings-card.js`) through the usual
   staged, SHA256-verified, backed-up sequence; the tool prints the resource reminder.
2. Register the Lovelace resource by hand: Settings -> Dashboards -> Resources -> Add, URL `/local/ecco/ecco-tou-settings-card.js`,
   type JavaScript module. No ECCO tool edits Home Assistant's `.storage`.
3. Stage and activate the dashboard (`tools/deploy-dashboard.ps1`; activation stays a deliberate step).
4. Read-only acceptance first: the table renders; one **Review only** on a slot that is not active behaves as the scripts say;
   **no Apply** until the owner authorises the first supervised one.

## Development

```bash
npm ci
npm test              # Node suites (node:test; a recording DOM shim and a recording Home Assistant object)
npm run typecheck     # tsc --noEmit
npm run build         # dist/ecco-tou-settings-card.js (deterministic: same sources -> same bytes)
```

Node 22.18+ runs the TypeScript tests directly (validated with Node 24). The build tools are pinned exactly (esbuild 0.28.1,
TypeScript 5.9.3). The CI wrapper `tools/tests/test_tou_settings_card.py` re-checks the service-call allow-list over the source and
the bundle, the reserved tokens, the site render, the dashboard and manifest integration, the contract texts against the ACS1
package, and runs this Node suite.

### Files

| Path | Purpose |
|---|---|
| `src/ecco-tou-settings-card.ts` | the custom element (events, regions, the `hass` setter that keeps `states` and the service function only) |
| `src/model.ts` | pure logic: configuration, entity ids, the ACS1 contract parsers (plan record, result text, phrase, edit records), blockers, eligibility, the editor state machine, spacing, Undo, progress |
| `src/actions.ts` | the only module that performs a call: the three allowed `script.turn_on` calls |
| `src/render.ts`, `src/styles.ts`, `src/types.ts` | HTML rendering (every value escaped), mobile-first styles, types |
| `test/` | Node suites: model, rendering, the element through the shim, static allow-list, build reproducibility |
| `dist/ecco-tou-settings-card.js` | the built bundle |

## License

GPL-3.0-or-later, the licence of the ECCO-Pro project. The card has no runtime dependencies.
