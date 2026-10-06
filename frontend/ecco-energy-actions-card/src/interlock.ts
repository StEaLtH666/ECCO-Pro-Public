// Pure sibling-interlock classification - no Lit, no DOM, no hass object.
// Same separation-of-concerns rule as freePowerState.ts/dumpState.ts: the
// firmware is the sole safety authority for mutual exclusion between Free
// Power and Dump to Grid (see the "REJECTED - ... owns inverter settings"
// preconditions in firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and
// docs/DUMP_TO_GRID_V1.md's "Free Power mutual exclusion (both directions)"
// section). This module only decides how to SHOW that a feature is
// currently unavailable because its sibling already owns the inverter - it
// never itself blocks or allows a service call; the firmware re-validates
// every precondition independently regardless of what this presents.
//
// There is no dedicated "who owns the inverter" entity exposed to Home
// Assistant today, so this reads the sibling's own already-computed visual
// state (classifyFreePower()/classifyDump()) rather than raw entity
// booleans - that keeps a single definition of "busy"/"active"/"recovery
// obligation" shared with each feature's own tile instead of re-deriving it
// here from scratch.

import type { FreePowerVisualState } from "./freePowerState";
import type { DumpVisualState } from "./dumpState";

export type InterlockableVisualState = FreePowerVisualState | DumpVisualState;

// Visual states that represent a LIVE, CURRENT inverter ownership/recovery
// obligation on the sibling feature - as opposed to a merely scheduled/armed
// FUTURE action, which must never trigger sibling interlock. A confirmed
// schedule can only ever upgrade the sibling's plain "ready" state (see
// resolveDisplayState()/resolveDumpDisplayState()), so "ready" never appears
// here even while the sibling has a schedule armed for later - matching the
// task rule that a future scheduled action alone must not globally
// interlock the other feature right now.
//   - active               - the sibling currently owns the inverter, running
//   - busy                 - mid-transaction (starting/restoring/verifying)
//   - recovery_attention   - firmware says an operator decision/recovery is required
//   - deferred             - a durable restore obligation (or watchdog retry) is outstanding
const OWNS_INVERTER_STATES: ReadonlySet<InterlockableVisualState> = new Set([
  "active",
  "busy",
  "recovery_attention",
  "deferred",
]);

/** Whether the sibling feature currently has live inverter ownership or a recovery obligation. `null` (sibling not configured/unavailable) is never treated as ownership. */
export function siblingOwnsInverter(siblingVisualState: InterlockableVisualState | null): boolean {
  return siblingVisualState !== null && OWNS_INVERTER_STATES.has(siblingVisualState);
}

/**
 * Whether THIS feature should show as INTERLOCKED. State-priority rule: this
 * can only ever apply while this feature's own visual state is the plain
 * "ready" or "armed" - every other own state (unavailable, recovery
 * attention, deferred, busy, active) is this card's own authoritative
 * hardware state and always outranks sibling interlock, so it is never
 * reinterpreted just because the sibling also happens to own the inverter.
 */
export function isInterlocked(
  ownVisualState: InterlockableVisualState,
  siblingVisualState: InterlockableVisualState | null
): boolean {
  const ownIsIdleOrArmed = ownVisualState === "ready" || ownVisualState === "armed";
  return ownIsIdleOrArmed && siblingOwnsInverter(siblingVisualState);
}

/** Gates an already-computed control-enabled boolean (e.g. canStartFreePower(state)) behind interlock, without disturbing any of its other rules. */
export function canActWhileInterlocked(baseAllowed: boolean, interlocked: boolean): boolean {
  return baseAllowed && !interlocked;
}

/**
 * Concise, non-alarming wording for why this feature is interlocked, keyed
 * off the sibling's own visual state - never implies a fault with THIS
 * feature. `siblingLabel` is the sibling's product name ("Free Power" /
 * "Dump to Grid"), so callers own capitalisation/wording of the feature name.
 */
export function interlockMessage(
  siblingLabel: string,
  siblingVisualState: InterlockableVisualState | null
): string {
  switch (siblingVisualState) {
    case "busy":
      return `${siblingLabel} is restoring inverter state.`;
    case "recovery_attention":
    case "deferred":
      return `${siblingLabel} requires recovery before this can be used.`;
    default:
      return `${siblingLabel} currently owns inverter control.`;
  }
}
