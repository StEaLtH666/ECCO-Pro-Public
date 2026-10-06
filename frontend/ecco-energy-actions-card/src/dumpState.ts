// Pure classification logic for the Dump to Grid tile - mirrors
// freePowerState.ts exactly (same shape, same reasoning), adapted for
// Dump-to-Grid V1's own firmware status vocabulary. Kept separate from the
// component so it can be unit tested directly (see test/dumpState.test.ts).
//
// IMPORTANT: this is presentation classification only. It never decides
// whether an inverter write is safe - the firmware is the sole authority on
// that (see firmware/ecco_clock_dongle_stage3_4_free_power.yaml's own
// REJECTED/DEFERRED precondition checks for start_dump_to_grid_override /
// restore_dump_to_grid_snapshot, which this file's regexes are read
// directly off of). This module only decides how to SHOW whatever the
// firmware already decided.
//
// Scheduling (2026-09-26 pre-live hardening): the card's Dump tile has the
// same NOW/LATER selector as Free Power, driving
// home-assistant/packages/ecco_dump_to_grid_schedule.yaml's helpers - see
// resolveDumpDisplayState() below for how a confirmed-armed schedule is shown.

export type DumpVisualState =
  | "unavailable"
  | "recovery_attention"
  | "deferred"
  | "busy"
  | "active"
  | "armed"
  | "ready";

export interface DumpClassifyInput {
  /** binary_sensor.*_dump_to_grid_active - null when the entity is unavailable/unknown. */
  active: boolean | null;
  /** switch.*_dump_to_grid_write_enable - null when the entity is unavailable/unknown. */
  armed: boolean | null;
  /** binary_sensor.*_dump_to_grid_operation_in_progress - null when the entity is unavailable/unknown. */
  operationInProgress: boolean | null;
  /** binary_sensor.*_dump_to_grid_snapshot_valid - true while a durable restore obligation is outstanding; null when unavailable/unknown. */
  snapshotValid: boolean | null;
  /** sensor.*_dump_to_grid_status - the firmware's own literal text, verbatim. */
  statusText: string | undefined;
}

// Matched directly against the literal strings
// start_dump_to_grid_override/restore_dump_to_grid_snapshot publish
// - never invented wording of our own. Deliberately NOT matching the bare
// word "REJECTED": a rejected START (e.g. "REJECTED - arm Dump to Grid
// Write Enable first") means the system is still perfectly safe and idle.
//
// 2026-09-26 final pre-OTA review fix: "ACCEPT REFUSED - <reason>" and
// "REJECTED - arm Dump to Grid Recovery Arm first" are only ever published
// by the operator recovery buttons while dump_operator_needed and
// dump_snapshot_valid are both true (a durable lockout). Without matching
// them here they fell through to the boolean states - "active" whenever the
// lockout followed an ACTIVE lease (dump_active_persisted stays true until a
// verified restore) - so the tile showed "Active / Exporting up to N W" with
// no recovery controls until the next 15s watchdog tick republished
// OPERATOR DECISION REQUIRED.
const ATTENTION_PATTERN =
  /RECOVERY REQUIRED|OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first|RESTORE BLOCKED|RECOVERY BLOCKED|\bFAILED\b|VERIFY ERROR|VERIFY TIMEOUT|VERIFY REFUSED/i;
const DEFERRED_PATTERN = /DEFERRED/i;
const BUSY_PATTERN = /^(RESTORING|STARTING)/i;

/**
 * Resolves the tile's single visual state. Priority (highest first):
 *   1. unavailable - can't trust anything else if the core entities aren't there
 *   2. recovery_attention - firmware said so, in those words, regardless of the booleans
 *   3. deferred - watchdog will retry, nothing for the user to do
 *   4. busy - a transaction is genuinely in flight (starting/restoring)
 *   5. active / armed / ready - the plain boolean-driven states
 *
 * 2026-09-26 independent-review fix: "ready"/"armed" additionally require
 * snapshotValid === false. The status text is only the LAST string the
 * firmware published (e.g. "REJECTED - saved snapshot pending
 * restore/recovery" after a Start press while an obligation is
 * outstanding), so without this the tile could show Ready - with Arm/Start
 * enabled - while the firmware still holds a restore obligation. An
 * outstanding obligation with no more specific status maps to "deferred"
 * (the watchdog owns it); an unknown snapshot state is "unavailable".
 */
export function classifyDump(input: DumpClassifyInput): DumpVisualState {
  const { active, armed, operationInProgress, snapshotValid, statusText } = input;

  if (active === null || armed === null || operationInProgress === null || snapshotValid === null) {
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
  if (snapshotValid) {
    return "deferred";
  }
  if (armed) {
    return "armed";
  }
  return "ready";
}

/** START is enabled ONLY from the plain "armed" state - same UI-only gate rationale as canStartFreePower. */
export function canStartDump(state: DumpVisualState): boolean {
  return state === "armed";
}

/**
 * END & RESTORE stays available in every state except "busy" (already
 * mid-transaction) and "unavailable" (nothing to call safely) - same
 * rationale as canEndRestore, including staying enabled in
 * "recovery_attention" since that is the documented recovery step for
 * several Dump status strings too.
 */
export function canEndDump(state: DumpVisualState): boolean {
  return state !== "busy" && state !== "unavailable";
}

/** ARM (the write-enable switch) is only ever toggled from a fully idle/armed state - never mid-transaction. */
export function canToggleDumpArm(state: DumpVisualState): boolean {
  return state === "ready" || state === "armed";
}

const STATE_LABELS: Record<DumpVisualState, string> = {
  unavailable: "Unavailable",
  recovery_attention: "Attention Needed",
  deferred: "Waiting For Inverter",
  busy: "Working",
  active: "Active",
  armed: "Armed",
  ready: "Ready",
};

export function dumpStateLabel(state: DumpVisualState): string {
  return STATE_LABELS[state];
}

// ---------------------------------------------------------------------
// 2026-09-26 pre-live hardening: schedule, latched-value and recovery
// presentation helpers. Pure functions, same separation of concerns as
// schedule.ts for Free Power.
// ---------------------------------------------------------------------

// "interlocked" (2026-09-26 sibling card polish) is a separate overlay this
// type also carries so callers can share one display-state variable, but it
// is layered on afterwards by interlock.ts's isInterlocked() - never
// produced by resolveDumpDisplayState() below, which only ever knows about
// this one feature's own schedule.
export type DumpDisplayState = DumpVisualState | "scheduled" | "interlocked";

/**
 * Same priority rule as schedule.ts's resolveDisplayState() for Free Power:
 * a CONFIRMED armed schedule may only upgrade the plain "ready" state.
 * Every hardware/safety state (unavailable, attention, deferred, busy,
 * active, manually armed) passes through untouched, so a schedule can never
 * conceal an outstanding restore obligation.
 */
export function resolveDumpDisplayState(state: DumpVisualState, scheduleArmed: boolean | null): DumpDisplayState {
  if (state === "ready" && scheduleArmed === true) {
    return "scheduled";
  }
  return state;
}

export function dumpDisplayStateLabel(state: DumpDisplayState): string {
  if (state === "scheduled") return "Scheduled";
  if (state === "interlocked") return "Interlocked";
  return dumpStateLabel(state);
}

// 2026-09-26 adversarial review (M3): the firmware's own status wording
// changed from V1's "exporting up to NW" to V1.1's "target NW export -
// <STATE> - battery ceiling NW" - see dump_controller_tick and
// start_dump_to_grid_override's own status snprintf calls. This captures
// the TARGET (what resolveLatchedExportPower means - the fixed,
// user-requested net grid export), not the dynamically-adjusted ceiling.
const LATCHED_POWER_IN_STATUS = /target (\d+)\s*W export/i;
const LATCHED_STOP_SOC_IN_STATUS = /Stop SOC (\d+)\s*%/i;

/**
 * The Export Power the RUNNING lease actually uses. Prefers the firmware's
 * latched-value sensor; falls back to the value embedded in the firmware's
 * own "ACTIVE - VERIFIED OK; target NW export - <STATE> - battery ceiling
 * NW; Stop SOC N%" status text. Deliberately NEVER falls back to the staged
 * number entity - that can be edited while a lease runs and is not what the
 * inverter was set to. Returns null when the latched value is unknown.
 */
export function resolveLatchedExportPower(latchedSensor: number | null, statusText: string | undefined): number | null {
  if (latchedSensor !== null && Number.isFinite(latchedSensor)) return latchedSensor;
  const m = statusText ? LATCHED_POWER_IN_STATUS.exec(statusText) : null;
  return m ? Number(m[1]) : null;
}

/** Same as resolveLatchedExportPower(), for the Stop SOC the firmware watchdog enforces. */
export function resolveLatchedStopSoc(latchedSensor: number | null, statusText: string | undefined): number | null {
  if (latchedSensor !== null && Number.isFinite(latchedSensor)) return latchedSensor;
  const m = statusText ? LATCHED_STOP_SOC_IN_STATUS.exec(statusText) : null;
  return m ? Number(m[1]) : null;
}

const OPERATOR_RECOVERY_PATTERN = /OPERATOR DECISION REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;

/**
 * Whether to show the operator recovery controls (Recovery Arm / Force
 * Restore Original / Accept Current State). Only while the firmware has
 * said an operator decision is needed (or just refused an Accept) AND a
 * durable obligation still exists - never as a general-purpose shortcut.
 * The firmware re-checks every precondition itself.
 */
export function dumpRecoveryControlsVisible(statusText: string | undefined, snapshotValid: boolean | null): boolean {
  return snapshotValid === true && !!statusText && OPERATOR_RECOVERY_PATTERN.test(statusText);
}
