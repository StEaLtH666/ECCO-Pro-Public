// Shared test fixtures: a mocked Home Assistant `states` map for every entity the card reads, in an idle, healthy state, and
// helpers to vary it. The slot layout is the reference site's (REPORTED in the project record): it wraps midnight, so the
// start-time rule (L1) is exercised by default.
import {
  DEFAULT_ENTITY_PREFIX,
  H_DG_ARMED,
  H_DG_START,
  H_FP_ARMED,
  H_FP_START,
  H_IN_FLIGHT,
  H_LOCK,
  H_OWNER_EDIT,
  H_PLAN,
  H_RESERVE,
  H_RESULT,
  H_WRITE_SEEN,
  SCRIPT_ACK,
  SCRIPT_APPLY,
  SCRIPT_REVIEW,
  dongleIds,
  formatLondonWall,
  normalizeConfig,
  slotIds,
} from "../src/model.ts";
import type { CardConfig, HassEntityLike, StatesLike } from "../src/types.ts";

/** Sunday 25 October 2026, 14:00 UTC (the UK is on GMT from 01:00 that day). */
export const NOW = Date.parse("2026-10-25T14:00:00Z");
export const PREFIX = DEFAULT_ENTITY_PREFIX;

export const STARTS = ["00:30", "05:30", "12:00", "16:35", "22:00", "00:25"];
export const POWERS = ["8000", "8000", "8000", "8000", "8000", "8000"];
export const SOCS = ["100", "100", "20", "100", "20", "100"];
export const SOURCES = ["Grid", "None", "None", "None", "None", "Grid"];

export const ACK_TEXT = "ACKNOWLEDGED - the owner checked the TOU slots; edits unlocked";
export const APPLIED_TEXT = "APPLIED AND VERIFIED - slot 3 target SOC 20 % -> 90 %: firmware readback and an independent later read of every written register agree";
export const OWNER_EDIT_TEXT = "2026-10-25 13:55:10 slot 3 target SOC (register 270) 20 % -> 90 % (owner, Advanced Configuration)";

export function iso(msAgo: number, now = NOW): string {
  return new Date(now - msAgo).toISOString();
}

/** The dongle's own Last Configuration Update form: a naive Europe/London wall time, `YYYY-MM-DD HH:MM:SS`. */
export function wall(msAgo: number, now = NOW): string {
  return formatLondonWall(now - msAgo);
}

export function config(over: Record<string, unknown> = {}): CardConfig {
  return normalizeConfig({ type: "custom:ecco-tou-settings-card", ...over });
}

export function ent(state: string, msAgo = 5000, attributes: Record<string, unknown> = {}, now = NOW): HassEntityLike {
  const ts = iso(msAgo, now);
  return { state, attributes, last_changed: ts, last_updated: ts, last_reported: ts };
}

/** An idle, healthy world: six fresh slots, the editor idle (last result ACKNOWLEDGED two hours ago), nothing owning the TOU settings. */
export function baseStates(prefix = PREFIX, now = NOW): StatesLike {
  const s: StatesLike = {};
  const d = dongleIds(prefix);
  for (let n = 1; n <= 6; n++) {
    const ids = slotIds(prefix, n);
    s[ids.time] = ent(STARTS[n - 1] ?? "", 20_000, {}, now);
    s[ids.power] = ent(POWERS[n - 1] ?? "", 20_000, { unit_of_measurement: "W" }, now);
    s[ids.soc] = ent(SOCS[n - 1] ?? "", 20_000, { unit_of_measurement: "%" }, now);
    s[ids.charge] = ent(SOURCES[n - 1] ?? "", 20_000, {}, now);
    s[ids.mode] = ent("General", 20_000, {}, now);
    s[ids.flags] = ent("1", 20_000, {}, now);
  }
  s[d.configUpdate] = ent(wall(20_000, now), 20_000, {}, now);
  s[d.configOnline] = ent("on", 20_000, {}, now);
  s[d.telemetryOnline] = ent("on", 5000, {}, now);
  s[d.cacheValid] = ent("on", 20_000, {}, now);
  for (const id of [d.fpActive, d.fpOp, d.fpSnapshot, d.dgActive, d.dgOp, d.dgSnapshot, d.writeInProgress, d.rtcInProgress]) s[id] = ent("off", 60_000, {}, now);
  for (const id of [d.writeEnable, d.fpWriteEnable, d.fpRecoveryArm, d.dgWriteEnable, d.dgRecoveryArm]) s[id] = ent("off", 60_000, {}, now);
  s[d.shutdownSoc] = ent("20", 20_000, { unit_of_measurement: "%" }, now);
  s[d.heartbeatAge] = ent("4.2", 2000, { unit_of_measurement: "s" }, now);
  s[d.supervisionStable] = ent("on", 60_000, {}, now);
  s[d.manualLastResult] = ent("Manual staging loaded from current inverter Slot 1 (reference)", 3_600_000, {}, now);
  s[d.writeAttempts] = ent("6", 30_000, {}, now);
  s[d.loadLimit] = ent("Zero Export", 20_000, {}, now);
  s[d.touEnabled] = ent("on", 20_000, {}, now);
  s[d.inverterTime] = ent(iso(1000, now), 1000, {}, now);
  s[SCRIPT_REVIEW] = ent("off", 3_600_000, {}, now);
  s[SCRIPT_APPLY] = ent("off", 3_600_000, {}, now);
  s[SCRIPT_ACK] = ent("off", 3_600_000, {}, now);
  s[H_PLAN] = ent("used", 7_200_000, {}, now);
  s[H_RESULT] = ent(ACK_TEXT, 7_200_000, {}, now);
  s[H_OWNER_EDIT] = ent("2026-10-25 11:55:10 slot 1 target SOC (register 268) 99 % -> 100 % (owner, Advanced Configuration)", 7_200_000, {}, now);
  s[H_LOCK] = ent("off", 7_200_000, {}, now);
  s[H_IN_FLIGHT] = ent("off", 7_200_000, {}, now);
  s[H_WRITE_SEEN] = ent("on", 7_200_000, {}, now);
  s[H_RESERVE] = ent("5", 86_400_000, {}, now);
  s[H_FP_ARMED] = ent("off", 86_400_000, {}, now);
  s[H_FP_START] = ent("2026-10-26 02:00:00", 86_400_000, {}, now);
  s[H_DG_ARMED] = ent("off", 86_400_000, {}, now);
  s[H_DG_START] = ent("2026-10-26 14:00:00", 86_400_000, {}, now);
  return s;
}

export function withEntity(states: StatesLike, id: string, e: HassEntityLike | undefined): StatesLike {
  const copy: StatesLike = { ...states };
  if (e === undefined) delete copy[id];
  else copy[id] = e;
  return copy;
}

export function withState(states: StatesLike, id: string, state: string, msAgo = 5000, attributes?: Record<string, unknown>): StatesLike {
  const prev = states[id];
  return withEntity(states, id, ent(state, msAgo, attributes ?? prev?.attributes ?? {}));
}

/** A plan record reviewed `agoS` seconds ago with the REVIEWED result text the package writes for it. */
export function reviewed(states: StatesLike, slot: number, setting: string, want: string, before: string, code = "4321", agoS = 30): StatesLike {
  const reviewedAt = Math.floor(NOW / 1000) - agoS;
  const label = { target_soc: "target SOC", power: "power", charge_source: "charge source", start_time: "start time" }[setting] ?? setting;
  const disp = (v: string): string => (setting === "target_soc" ? `${v} %` : setting === "power" ? `${v} W` : v);
  const phr = setting === "target_soc" ? `TARGET SOC ${want}` : setting === "power" ? `POWER ${want} W` : `CHARGE SOURCE ${want.toUpperCase()}`;
  const reg = ({ target_soc: 267, power: 255, charge_source: 273, start_time: 249 }[setting] ?? 0) + slot;
  let s = withState(states, H_PLAN, `${slot}|${setting}|${want}|${code}|${reviewedAt}|${before}`, agoS * 1000);
  s = withState(s, H_RESULT, `REVIEWED - slot ${slot} ${label} (register ${reg}) ${disp(before)} -> ${disp(want)}; confirm with: SET SLOT ${slot} ${phr} REVIEW ${code}`, agoS * 1000);
  return s;
}

/** Home Assistant frontend-shaped states: no `last_reported` anywhere; the given ids last changed `agoMs` ago (an unchanged value keeps
 *  the time it last changed, because the dongle re-publishes a slot value only when it changes). */
export function frontendLike(states: StatesLike, oldIds: string[], agoMs: number): StatesLike {
  const out: StatesLike = {};
  for (const [id, e] of Object.entries(states)) {
    if (!e) continue;
    const { last_reported: _lr, ...rest } = e;
    void _lr;
    out[id] = oldIds.includes(id) ? { ...rest, last_changed: iso(agoMs), last_updated: iso(agoMs) } : rest;
  }
  return out;
}

export const ALL_SLOT_IDS: string[] = [1, 2, 3, 4, 5, 6].flatMap((n) => Object.values(slotIds(PREFIX, n)));

export function applied(states: StatesLike, agoS = 3600): StatesLike {
  let s = withState(states, H_RESULT, APPLIED_TEXT, agoS * 1000);
  s = withState(s, H_OWNER_EDIT, OWNER_EDIT_TEXT, agoS * 1000);
  s = withState(s, slotIds(PREFIX, 3).soc, "90", 20_000, { unit_of_measurement: "%" });
  return s;
}
