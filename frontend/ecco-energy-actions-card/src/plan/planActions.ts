// Plan actions (stage 3): the CLOSED list of service calls the plan section can make, and nothing else.
//
//   * Every call is `script.turn_on` on one of three guarded Home Assistant scripts: the override start, the override cancel
//     (home-assistant/packages/ecco_plan_helpers.yaml) and, when the card is configured with `dump_to_grid.guarded_start`, the guarded
//     manual Dump to Grid start (home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml). The scripts, not this card, decide: they
//     enforce the owner's limits, the expiry, the raise-only reserve and the hold server-side, and write only the plan helpers.
//   * The card never writes a helper, a charge, a discharge, a time-of-use or an inverter entity from the plan section.
//   * `isPlanServiceCall` is the allow-list: the card drops any call that is not exactly one of the three, whoever built it.
// Pure: no DOM, no Lit, no Home Assistant object, no clock, no storage. It builds data; the card is what sends it.
import type { OverrideKind } from "../../../ecco-plan-core/src/index.ts";

// The entities the plan section reads and calls beyond the helpers of helpers.ts. The block between the markers is strict JSON (a Python
// test reads it and checks the helper package defines exactly these).
// BEGIN PLAN_CONTROL_IDS_JSON
export const PLAN_CONTROL_IDS = {
  "last_result": "input_text.ecco_plan_last_result",
  "start_script": "script.ecco_plan_override_start",
  "cancel_script": "script.ecco_plan_override_cancel"
} as const;
// END PLAN_CONTROL_IDS_JSON

/** One service call, as data. Its domain and service are fixed: the plan section can only run a script. */
export interface PlanServiceCall {
  readonly domain: "script";
  readonly service: "turn_on";
  readonly data: { readonly entity_id: string; readonly variables?: Readonly<Record<string, unknown>> };
}

export interface StartChoice {
  /** A length in whole minutes. */
  expiryMin?: number;
  /** Until the owner's end time (Hold battery and Skip tonight): the script works the minutes out on its own clock. */
  untilLocal?: boolean;
}

/** Start an override. The caller's choice is passed as it is; the script validates it again, server-side. */
export function startOverrideCall(kind: OverrideKind, choice: StartChoice, expectedRevision: number | null): PlanServiceCall {
  const variables: Record<string, unknown> = { kind };
  if (choice.untilLocal === true) variables["until_local"] = true;
  else if (typeof choice.expiryMin === "number") variables["expiry_min"] = choice.expiryMin;
  if (typeof expectedRevision === "number") variables["expected_revision"] = expectedRevision;
  return { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script, variables } };
}

export function cancelOverrideCall(kind: OverrideKind, expectedRevision: number | null): PlanServiceCall {
  const variables: Record<string, unknown> = { kind };
  if (typeof expectedRevision === "number") variables["expected_revision"] = expectedRevision;
  return { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.cancel_script, variables } };
}

/** The manual Dump to Grid start through its guarded script (a script entity id from the card's own configuration). */
export function guardedDumpStartCall(scriptId: string): PlanServiceCall | null {
  return /^script\.[a-z0-9_]+$/.test(scriptId) ? { domain: "script", service: "turn_on", data: { entity_id: scriptId } } : null;
}

/**
 * The allow-list. True only for `script.turn_on` on the override start, the override cancel or the configured guarded Dump to Grid start,
 * with no data other than `entity_id` and `variables` and no variable other than the four the scripts take.
 */
export function isPlanServiceCall(call: unknown, guardedStartId: string | null | undefined): boolean {
  if (typeof call !== "object" || call === null) return false;
  const c = call as { domain?: unknown; service?: unknown; data?: unknown };
  if (c.domain !== "script" || c.service !== "turn_on") return false;
  if (typeof c.data !== "object" || c.data === null) return false;
  const d = c.data as { entity_id?: unknown; variables?: unknown };
  if (Object.keys(c.data).some((k) => k !== "entity_id" && k !== "variables")) return false;
  const id = d.entity_id;
  const isGuardedStart = typeof guardedStartId === "string" && guardedStartId !== "" && id === guardedStartId;
  if (id !== PLAN_CONTROL_IDS.start_script && id !== PLAN_CONTROL_IDS.cancel_script && !isGuardedStart) return false;
  if (d.variables === undefined) return true;
  if (typeof d.variables !== "object" || d.variables === null || isGuardedStart) return false;
  return Object.keys(d.variables).every((k) => k === "kind" || k === "expiry_min" || k === "until_local" || k === "expected_revision");
}
