// Pure Scheduled Free Power presentation/classification logic - no Lit, no
// DOM, no hass object. Mirrors freePowerState.ts's separation of concerns:
// this module decides how to SHOW the existing, already-authoritative
// home-assistant/packages/ecco_free_power_schedule.yaml package - it never
// duplicates that package's own validation/automation logic, and it never
// arms firmware write_enable directly (see scheduleArmServiceCall()below -
// it only ever targets the existing input_boolean the HA automation already
// watches).
//
// IMPORTANT ordering guarantee this module exists to uphold: a schedule is
// only ever shown as armed once Home Assistant's own
// ecco_free_power_schedule_arm_validation automation has actually left the
// input_boolean ON. Arming can be silently rejected (the automation turns
// it back off and records why in last_result) - callers must render the
// banner from the CONFIRMED `armed` entity state only, never optimistically
// the instant a service call is issued. See classifySchedule().

import type { FreePowerVisualState } from "./freePowerState";

export interface ScheduleEntitiesState {
  /** input_boolean.ecco_free_power_schedule_armed - null when unavailable/unknown. */
  armed: boolean | null;
  /** input_datetime.ecco_free_power_schedule_start state, "YYYY-MM-DD HH:MM:SS". */
  startText: string | undefined;
  /** input_number.ecco_free_power_schedule_duration, minutes. */
  durationMin: number | null;
  /** input_number.ecco_free_power_schedule_power, watts. */
  powerW: number | null;
  /** input_text.ecco_free_power_schedule_last_result - the literal last outcome, verbatim. */
  lastResult: string | undefined;
}

export type ScheduleBannerState = "hidden" | "armed";

/**
 * Whether the persistent schedule banner should show. Confirmed-state-only
 * by design (see the module doc comment) - `armed` here must already be the
 * post-automation-validation entity value, never an optimistic local guess.
 */
export function classifySchedule(state: Pick<ScheduleEntitiesState, "armed">): ScheduleBannerState {
  return state.armed === true ? "armed" : "hidden";
}

/** True when the most recent schedule attempt was rejected by the HA validation automation (and nothing has since re-armed successfully). */
export function isScheduleRejected(lastResult: string | undefined): boolean {
  return !!lastResult && /^REJECTED/i.test(lastResult.trim());
}

/** True when the most recent schedule outcome is a firmware/automation-side block distinct from a plain rejection (e.g. "BLOCKED - ..."). */
export function isScheduleBlocked(lastResult: string | undefined): boolean {
  return !!lastResult && /^BLOCKED/i.test(lastResult.trim());
}

/**
 * Start/power/duration editing locks while a schedule is armed - cancel,
 * edit, re-arm is the only path, so an already-validated schedule is never
 * silently mutated out from under the automation that validated it.
 */
export function scheduleFieldsLocked(armed: boolean | null): boolean {
  return armed === true;
}

/**
 * Layers the confirmed-armed schedule on top of the existing, unmodified
 * top-level Free Power classification - ONLY when that classification is
 * the plain "ready" state. Every other state (unavailable, recovery
 * attention, deferred, busy, active, manual armed) is hardware/safety
 * information that must never be concealed or reinterpreted by schedule
 * cosmetics, so they pass through completely unchanged. This is the entire
 * implementation of the task's requested display priority: "UNAVAILABLE /
 * RECOVERY ATTENTION / DEFERRED / BUSY, then ACTIVE, then manual ARMED,
 * then SCHEDULED, then READY".
 *
 * "interlocked" (2026-09-26 sibling card polish) is a separate overlay this
 * type also carries so callers can share one display-state variable, but it
 * is layered on afterwards by interlock.ts's isInterlocked() - never
 * produced by resolveDisplayState() below, which only ever knows about this
 * one feature's own schedule.
 */
export type FreePowerDisplayState = FreePowerVisualState | "scheduled" | "interlocked";

export function resolveDisplayState(
  freePowerState: FreePowerVisualState,
  scheduleBanner: ScheduleBannerState
): FreePowerDisplayState {
  if (freePowerState === "ready" && scheduleBanner === "armed") {
    return "scheduled";
  }
  return freePowerState;
}

// ---------------------------------------------------------------------
// Service call builders - pure data, no hass.callService side effects, so
// the domain/service/entity mapping itself is unit-testable without a DOM
// or a mock hass object. Every one of these targets ONLY the existing
// entities/script the ecco_free_power_schedule.yaml package already owns;
// none of them touch switch.*_free_power_write_enable or any other manual
// Free Power entity - see test/schedule.test.ts's "manual Arm and schedule
// Arm remain distinct" case.
// ---------------------------------------------------------------------

export interface ServiceCall {
  domain: string;
  service: string;
  data: Record<string, unknown>;
}

/** Arms the SCHEDULE only - input_boolean.turn_on on the schedule's own armed helper. Never switch.turn_on on the manual write_enable switch. */
export function scheduleArmServiceCall(entityId: string): ServiceCall {
  return { domain: "input_boolean", service: "turn_on", data: { entity_id: entityId } };
}

/** Cancels via the existing script only - script.turn_on, never a duplicated inline cancellation sequence. */
export function scheduleCancelServiceCall(entityId: string): ServiceCall {
  return { domain: "script", service: "turn_on", data: { entity_id: entityId } };
}

/** Sets the scheduled start via the standard input_datetime.set_datetime service. `localTimestamp` must already be "YYYY-MM-DD HH:MM:SS" (see utils/time.ts's formatLocalTimestamp). */
export function scheduleSetStartServiceCall(entityId: string, localTimestamp: string): ServiceCall {
  return { domain: "input_datetime", service: "set_datetime", data: { entity_id: entityId, datetime: localTimestamp } };
}

/** Sets a scheduled numeric field (power or duration) via the standard input_number.set_value service. */
export function scheduleSetNumberServiceCall(entityId: string, value: number): ServiceCall {
  return { domain: "input_number", service: "set_value", data: { entity_id: entityId, value } };
}

/**
 * Resolves the effective max for the scheduled power control: the
 * input_number entity's own `max` attribute, clamped further down by
 * `sensor.ecco_free_power_schedule_status`'s `effective_power_limit_w`
 * attribute when that is present and lower - reusing the site's real
 * configured ceiling rather than only ever showing the input_number's
 * static schema max. Never raises the limit above the entity's own max.
 */
export function effectiveSchedulePowerMax(entityMax: number, effectivePowerLimitW: number | null): number {
  if (effectivePowerLimitW === null || !Number.isFinite(effectivePowerLimitW) || effectivePowerLimitW <= 0) {
    return entityMax;
  }
  return Math.min(entityMax, effectivePowerLimitW);
}
