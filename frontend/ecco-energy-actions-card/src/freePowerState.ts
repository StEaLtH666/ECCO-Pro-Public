// Pure classification logic for the Free Power tile - no Lit, no DOM, no
// hass object. Kept separate from the component so it can be unit tested
// directly (see test/freePowerState.test.ts) and so the actual UI state
// machine described in the task ("SAFE/READY, ARMED, ACTIVE, RESTORING,
// DEFERRED/WAITING, RECOVERY ATTENTION, UNAVAILABLE") lives in one obvious
// place rather than being scattered across render() branches.
//
// IMPORTANT: this is presentation classification only. It never decides
// whether an inverter write is safe - the firmware is the sole authority on
// that (see firmware/ecco_clock_dongle_stage3_4_free_power.yaml's own
// REJECTED/DEFERRED/BLOCKED precondition checks, which this file's regexes
// are read directly off of). This module only decides how to SHOW whatever
// the firmware already decided.

export type FreePowerVisualState =
  | "unavailable"
  | "recovery_attention"
  | "deferred"
  | "busy"
  | "active"
  | "armed"
  | "ready";

export interface FreePowerClassifyInput {
  /** binary_sensor.*_free_power_active - null when the entity is unavailable/unknown. */
  active: boolean | null;
  /** switch.*_free_power_write_enable - null when the entity is unavailable/unknown. */
  armed: boolean | null;
  /** binary_sensor.*_free_power_operation_in_progress - null when the entity is unavailable/unknown. */
  operationInProgress: boolean | null;
  /** sensor.*_free_power_status - the firmware's own literal text, verbatim. */
  statusText: string | undefined;
}

// Matched directly against the literal strings the firmware publishes (see
// the id(free_power_status).publish_state(...) call sites in
// firmware/ecco_clock_dongle_stage3_4_free_power.yaml) - never invented
// wording of our own. Deliberately NOT matching the bare word "REJECTED":
// a rejected START attempt (e.g. "REJECTED - arm Free Power Write Enable
// first") means the system is still perfectly safe and idle, not that it
// needs recovery attention - see _renderFreePowerTile()'s handling of
// `statusText`, which always shows the literal text regardless of state so
// a REJECTED notice is never hidden, just not treated as an alarm.
const ATTENTION_PATTERN =
  /RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i;
const DEFERRED_PATTERN = /DEFERRED/i;
const BUSY_PATTERN = /^(RESTORING|STARTING|ACTIVATION VERIFY)/i;

/**
 * Resolves the tile's single visual state. Priority (highest first):
 *   1. unavailable - can't trust anything else if the core entities aren't there
 *   2. recovery_attention - firmware said so, in those words, regardless of the booleans
 *   3. deferred - watchdog will retry, nothing for the user to do
 *   4. busy - a transaction is genuinely in flight (starting/restoring/verifying)
 *   5. active / armed / ready - the plain boolean-driven states
 */
export function classifyFreePower(input: FreePowerClassifyInput): FreePowerVisualState {
  const { active, armed, operationInProgress, statusText } = input;

  if (active === null || armed === null || operationInProgress === null) {
    return "unavailable";
  }
  if (statusText && ATTENTION_PATTERN.test(statusText)) {
    return "recovery_attention";
  }
  if (statusText && DEFERRED_PATTERN.test(statusText)) {
    return "deferred";
  }
  if (statusText && BUSY_PATTERN.test(statusText)) {
    return "busy";
  }
  if (active) {
    return "active";
  }
  if (operationInProgress) {
    return "busy";
  }
  if (armed) {
    return "armed";
  }
  return "ready";
}

/**
 * START is enabled ONLY from the plain "armed" state - i.e. armed is on AND
 * nothing else (active/busy/deferred/attention/unavailable) is already
 * going on. This is a UI-only gate for ergonomics (don't show an enabled
 * button that firmware would reject anyway); the firmware re-validates
 * every one of its own preconditions independently and remains the actual
 * safety authority (see the REJECTED - ... precondition chain in
 * firmware/ecco_clock_dongle_stage3_4_free_power.yaml).
 */
export function canStartFreePower(state: FreePowerVisualState): boolean {
  return state === "armed";
}

/**
 * END & RESTORE NOW stays available in every state except the two where
 * issuing it would be meaningless or would race an in-flight transaction:
 * "busy" (something is already mid-transaction) and "unavailable" (nothing
 * to call safely). It is deliberately still enabled in "recovery_attention"
 * - several of the firmware's own attention-worthy status strings (e.g.
 * "OPERATOR DECISION REQUIRED ... press End Free Power to retry") name this
 * exact button as the documented recovery step, so disabling it there would
 * remove the one safe action the firmware itself points the operator to.
 */
export function canEndRestore(state: FreePowerVisualState): boolean {
  return state !== "busy" && state !== "unavailable";
}

/** ARM (the write-enable switch) is only ever toggled from a fully idle/armed state - never mid-transaction. */
export function canToggleArm(state: FreePowerVisualState): boolean {
  return state === "ready" || state === "armed";
}

const STATE_LABELS: Record<FreePowerVisualState, string> = {
  unavailable: "Unavailable",
  recovery_attention: "Attention Needed",
  deferred: "Waiting For Inverter",
  busy: "Working",
  active: "Active",
  armed: "Armed",
  ready: "Ready",
};

export function freePowerStateLabel(state: FreePowerVisualState): string {
  return STATE_LABELS[state];
}
