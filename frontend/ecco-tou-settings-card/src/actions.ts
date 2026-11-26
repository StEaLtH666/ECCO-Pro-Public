// The ONLY module of this card that performs a Home Assistant service call.
//
// Exactly three calls exist, all `script.turn_on` with `variables`, each on one fixed ACS1 script entity (the three
// SCRIPT_* constants in model.ts):
//   review       {slot, setting, value}   writes nothing; the editor's real safety gate runs there
//   apply        {confirmation}           the typed phrase, checked again by the Apply script
//   acknowledge  {confirmation}           the typed phrase, checked again by the Acknowledge script
// `script.turn_on` returns at once; the card then observes the editor's helpers. No other service of any domain is named
// anywhere in this card, and no other module performs a call at all (test/static.test.ts pins both).
import { acknowledgeCall, applyCall, reviewCall } from "./model.ts";
import type { Draft, ServiceCall } from "./types.ts";

/** The shape of Home Assistant's service function (domain, service, data), handed in by the element's hass setter. */
export type CallFn = (domain: string, service: string, data?: Record<string, unknown>) => Promise<unknown>;

export type ActionKind = "review" | "apply" | "acknowledge";

function describe(kind: ActionKind, payload: Draft | string): ServiceCall {
  if (kind === "review") {
    if (typeof payload === "string") throw new Error("review needs a draft");
    return reviewCall(payload);
  }
  if (typeof payload !== "string") throw new Error(`${kind} needs the typed phrase`);
  return kind === "apply" ? applyCall(payload) : acknowledgeCall(payload);
}

/** Perform one of the three allowed calls. Returns the call made (for the card's own record) and its promise. */
export function perform(call: CallFn, kind: ActionKind, payload: Draft | string): { call: ServiceCall; done: Promise<unknown> } {
  const c = describe(kind, payload);
  const done = call(c.domain, c.service, { entity_id: c.data.entity_id, variables: c.data.variables });
  return { call: c, done };
}
