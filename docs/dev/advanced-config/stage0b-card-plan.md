# Advanced Configuration Stage 0b: editable card (PLAN; live write control NOT enabled)

**Goal:** the Advanced Configuration card (Inverter → Advanced) gets an editor for exactly one setting, the TOU slot target
SOC. It calls only the Stage 0 scripts. The card itself never writes or arms anything.

## UI stages

1. **Edit** (local only):
   - pick a slot (1-6) and a value;
   - show the live value, the allowed range (the greater of the inverter shutdown SOC and the ECCO reserve) and the register
     (267+N);
   - out-of-range values cannot be submitted;
   - no service call.
2. **Review** (one service call: `script.ecco_cfg_review_tou_slot_soc`):
   - the card shows the review result and the plan from `input_text.ecco_cfg_edit_review`: register, old → new, the unchanged
     values, the range and a 10-minute countdown;
   - nothing is armed.
3. **Confirm** (local):
   - the owner types the exact phrase `SET SLOT n TARGET SOC x REVIEW cccc`;
   - the Apply button stays disabled until the typed text matches exactly;
   - no autofill.
4. **Apply** (one service call: `script.ecco_cfg_apply_tou_slot_soc` with the typed phrase):
   - the card shows progress from `input_text.ecco_cfg_edit_last_result`, as phases (fresh read, Load, verify, independent
     read);
   - completion shows only on `APPLIED AND VERIFIED`;
   - FAILED, UNCERTAIN and the lock are shown prominently, with the recovery text;
   - while locked, the editor is disabled and points to the acknowledgement step;
   - no retry button.

## Card changes

- **New view-model:**
  - `edit` state machine: idle → reviewed → confirming → applying → result;
  - derived from entity states only, so the card stays stateless across reloads.
- **One narrow write allowance:** `hass.callService("script", …)` for the two script names, with exactly these fields
  (`slot`, `target_soc`; `confirmation`). Nothing else.
- **Feature flag:** `editable: false` by default in the card config, plus an overlay setting. While false, the editor renders
  read-only with "Stage 0b not enabled".

## Test changes (deliberate)

- **Relax** `frontend/ecco-advanced-config-card/test/static.test.ts`:
  - `callService` is allowed only with domain `script` and only those two service names;
  - `button.press`, `number.set_value`, `switch.turn_*`, `perform_action`, `dispatchEvent` and `setTimeout` stay banned.
- **New tests:**
  - the phrase gate;
  - review expiry;
  - the locked state;
  - no retry affordance;
  - completion only on `APPLIED AND VERIFIED`;
  - the feature flag defaults off.
- **Unchanged:** the Global Power (245) panel stays disabled, and every other record stays read-only (count pins unchanged).
- **Catalogue and Python suite:** the section [9] rule (which scope modules may name the card) needs the new entry's scope
  module added deliberately.

## Delivery

- **A separate post-export entry,** after Stage 0's live proof:
  - the card source, dist and tests (not frozen);
  - the dashboard card config, only if `editable` is set there (a frozen dashboard edit; otherwise none);
  - a manifest asset hash update.
- **Enabling the live write control** is a separate owner decision after both Stage 0's and Stage 0b's offline reviews.
