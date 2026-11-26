// Fixtures for the plan adapter and views: a readable six-slot table, Intelligence advice entities and the plan config.
import { BASE_CONFIG, P, idleStates } from "./fixtures.ts";
import type { States } from "./fixtures.ts";

export const PLAN_CONFIG = {
  entity_prefix: P,
  reserve: "input_number.ecco_minimum_reserve_soc",
  control_lock: "input_boolean.test_control_lock",
};

export const ADVICE = {
  status: "sensor.ecco_intel_status",
  charge_target: "sensor.ecco_intel_charge_target",
  export_event: "sensor.ecco_intel_export_event",
  pv_tomorrow: "sensor.ecco_intel_pv_tomorrow",
  fresh: "binary_sensor.ecco_intel_fresh",
  paused: "input_boolean.ecco_intel_paused",
};

export interface Slot {
  start: string;
  power: number;
  soc: number;
  charge: "Grid" | "None";
}

/** A valid six-slot day with exactly one grid-charge slot. */
export const TABLE: Slot[] = [
  { start: "00:00", power: 3000, soc: 20, charge: "None" },
  { start: "02:00", power: 5000, soc: 80, charge: "Grid" },
  { start: "05:00", power: 4000, soc: 30, charge: "None" },
  { start: "12:00", power: 3500, soc: 25, charge: "None" },
  { start: "17:00", power: 3200, soc: 35, charge: "None" },
  { start: "22:00", power: 2800, soc: 40, charge: "None" },
];

export function slotEntity(n: number, field: "time" | "power" | "soc" | "charge"): string {
  return `sensor.${P}_ecco_timezone${n}_${field}`;
}

export function withTable(s: States, table: Slot[] = TABLE): States {
  table.forEach((t, i) => {
    s[slotEntity(i + 1, "time")] = { state: t.start };
    s[slotEntity(i + 1, "power")] = { state: String(t.power) };
    s[slotEntity(i + 1, "soc")] = { state: String(t.soc) };
    s[slotEntity(i + 1, "charge")] = { state: t.charge };
  });
  return s;
}

export interface AdviceOpts {
  target?: number;
  importKwh?: number | null;
  exportKwh?: number | null;
  solarKwh?: number | null;
  confidence?: string;
  status?: string;
  fresh?: boolean;
  paused?: boolean;
}

export function withAdvice(s: States, o: AdviceOpts = {}): States {
  s[ADVICE.status] = { state: o.status ?? "OK" };
  s[ADVICE.fresh] = { state: o.fresh === false ? "off" : "on" };
  s[ADVICE.paused] = { state: o.paused ? "on" : "off" };
  s[ADVICE.charge_target] = {
    state: String(o.target ?? 80),
    attributes: {
      confidence: o.confidence ?? "HIGH",
      blockers: [],
      advice: { binding_constraint: "END_OF_PERIOD_FLOOR", conservative_fallback: false, net_need_kwh: 6.25, grid_charge_kwh: o.importKwh === undefined ? 4.5 : o.importKwh },
    },
  };
  s[ADVICE.export_event] = { state: o.exportKwh === null ? "unknown" : String(o.exportKwh ?? 2.2) };
  s[ADVICE.pv_tomorrow] = { state: o.solarKwh === null ? "unknown" : String(o.solarKwh ?? 11.4) };
  return s;
}

export function planConfig(extra: Record<string, unknown> = {}, plan: Record<string, unknown> = {}) {
  return { ...BASE_CONFIG, show_plan: true, plan: { ...PLAN_CONFIG, ...plan }, ...extra };
}

/** Idle card states + readable table + reserve helper (+ optional advice). */
export function planStates(withAdv = true, adv: AdviceOpts = {}): States {
  const s = withTable(idleStates());
  s[PLAN_CONFIG.reserve] = { state: "20" };
  s[PLAN_CONFIG.control_lock] = { state: "off" };
  if (withAdv) withAdvice(s, adv);
  return s;
}
