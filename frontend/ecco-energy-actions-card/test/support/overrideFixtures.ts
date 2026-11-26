// Fixtures for the plan-helper reader: a complete, confirmed policy (the proposed values, as an owner who accepted them would have
// set them) and override records written the way Home Assistant shows a date-and-time helper (local text plus a timestamp attribute).
import { HELPER_IDS } from "../../src/plan/helpers.ts";
import type { States } from "./fixtures.ts";

export const NOW_MS = Date.parse("2026-11-16T20:00:00Z");
export const NOW_MIN = Math.floor(NOW_MS / 60000);

const pad = (n: number) => (n < 10 ? "0" : "") + n;

/** A date-and-time helper state. The test treats the helper's local time as UTC; the reader must use the timestamp, not the text. */
export function stamp(epochMs: number, textOverride?: string): { state: string; attributes: { timestamp: number } } {
  const d = new Date(epochMs);
  const text = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  return { state: textOverride ?? text, attributes: { timestamp: epochMs / 1000 } };
}

export const NEVER = stamp(0);
export const MIN = 60_000;

// Owner decision r15 (19 Nov 2026): the absolute expiry record of each kind. The ids are restated here from the helper package, not taken from
// the card's HELPER_IDS, so a test that reads them proves the card names the package's entities.
export type KindName = "hold_battery" | "skip_tonight" | "prepare_power_cut";
export const KIND_NAMES: readonly KindName[] = ["hold_battery", "skip_tonight", "prepare_power_cut"];
export const EPOCH_ID = (kind: KindName): string => "input_number.ecco_plan_override_" + kind + "_expires_epoch";

/** The absolute expiry record of one kind: an instant in ms (shown as epoch seconds), a raw state text, or undefined (the entity does not exist: an older package). */
export function setEpoch(states: States, kind: KindName, value: number | string | undefined): States {
  const s = states as Record<string, unknown>;
  if (value === undefined) delete s[EPOCH_ID(kind)];
  else s[EPOCH_ID(kind)] = { state: typeof value === "number" ? String(value / 1000) : value };
  return states;
}

/** Every proposed helper present, policy = the proposed values, confirmed on, revision 12, no override running. */
export function helperStates(base: States, patch: Record<string, unknown> = {}): States {
  const s = base as Record<string, unknown>;
  const set = (key: keyof typeof HELPER_IDS, v: unknown) => {
    s[HELPER_IDS[key]] = v;
  };
  set("confirmed", { state: "on" });
  set("revision", { state: "12" });
  set("min_expiry", { state: "15" });
  set("hold_default", { state: "240" });
  set("hold_cap", { state: "1440" });
  set("skip_until", { state: "07:00:00" });
  set("skip_cap", { state: "1440" });
  set("cut_default", { state: "1440" });
  set("cut_cap", { state: "4320" });
  set("cut_reserve", { state: "80" });
  for (const k of ["hold_battery", "skip_tonight", "prepare_power_cut"] as const) {
    set((k + "_start") as keyof typeof HELPER_IDS, NEVER);
    set((k + "_expires") as keyof typeof HELPER_IDS, NEVER);
  }
  set("prepare_power_cut_reserve", { state: "10" });
  // Owner decision r15: the absolute expiry record of each kind, a fresh helper at its minimum (0: in the past), as Home Assistant restores it.
  for (const k of KIND_NAMES) s[EPOCH_ID(k)] = { state: "0" };
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) delete s[k];
    else s[k] = v;
  }
  return base;
}

/** Start and expiry records of one override, relative to NOW_MS. */
export function running(states: States, kind: "hold_battery" | "skip_tonight" | "prepare_power_cut", startedMinAgo: number, endsInMin: number, reserve?: number, nowMs: number = NOW_MS): States {
  const s = states as Record<string, unknown>;
  s[HELPER_IDS[(kind + "_start") as keyof typeof HELPER_IDS]] = stamp(nowMs - startedMinAgo * MIN);
  s[HELPER_IDS[(kind + "_expires") as keyof typeof HELPER_IDS]] = stamp(nowMs + endsInMin * MIN);
  if (reserve !== undefined) s[HELPER_IDS.prepare_power_cut_reserve] = { state: String(reserve) };
  return states;
}
