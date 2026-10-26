// Power model: the established ECCO Energy Flow logic, unchanged.
//
// The four sign/aggregation helpers below mirror
// frontend/ecco-energy-flow-card/src/config.ts exactly (same names, same
// semantics). test/parity.test.ts imports both modules and checks they
// agree on a vector set, so this card cannot drift from the approved
// behaviour without a test failing. Pure functions only: no Lit, no DOM.

import type { BatteryPowerSign, GridPowerSign } from "../config.ts";

/** Internal convention: positive = discharging (energy flowing OUT of the battery). */
export function normaliseBatteryPower(raw: number, sign: BatteryPowerSign | undefined): number {
  return sign === "discharge_positive" ? raw : -raw;
}

/** Internal convention: positive = importing (energy flowing FROM the grid). */
export function normaliseGridPower(raw: number, sign: GridPowerSign | undefined): number {
  return sign === "export_positive" ? -raw : raw;
}

/** Minimum derived-balance magnitude before a native Home reading of exactly 0 W is treated as unreliable. */
export const HOME_FALLBACK_MIN_W = 150;

/**
 * Home/load power resolution (Dump-to-Grid V1.1 investigation, 2026-09-26):
 * prefer the native reading whenever credible; fall back to
 * inverter AC output + grid power (import positive) only when native is
 * unavailable, or exactly 0 W while the balance clearly implies load.
 * Unknown when neither is available. Never negative.
 */
export function resolveHomeW(nativeW: number | null, inverterW: number | null, gridW: number | null): number | null {
  const derived = inverterW !== null && gridW !== null ? Math.max(0, inverterW + gridW) : null;
  if (nativeW === null) {
    return derived;
  }
  if (nativeW === 0 && derived !== null && derived > HOME_FALLBACK_MIN_W) {
    return derived;
  }
  return Math.max(0, nativeW);
}

/**
 * Combined PV power without double counting. The configured total entity
 * is authoritative when it has a value. Otherwise the sum of the arrays
 * that currently have a value (a real sum of real readings); unknown when
 * no array has a value.
 */
export function aggregateSolarW(totalW: number | null, arrayW: Array<number | null>): number | null {
  if (totalW !== null) return Math.max(0, totalW);
  const known = arrayW.filter((w): w is number => w !== null);
  if (known.length === 0) return null;
  return Math.max(
    0,
    known.reduce((a, b) => a + b, 0)
  );
}

/** Below this magnitude a flow is idle (no movement). Same value as the Energy Flow card. */
export const IDLE_THRESHOLD_W = 5;

export type FlowId = "solar" | "battery" | "grid" | "home";

/**
 * One animated path in the scene. `forward` is the canonical direction of
 * the drawn path (solar -> inverter, battery -> inverter, grid -> inverter,
 * inverter -> home); `reversed` means energy currently travels the other
 * way (battery charging, grid exporting). The path geometry never changes
 * with direction; only the travel direction and colour do.
 */
export interface FlowEdge {
  id: FlowId;
  /** Magnitude in W, or null when the reading is unknown. */
  magnitudeW: number | null;
  /** True when the reading is known and below IDLE_THRESHOLD_W. */
  idle: boolean;
  /** True when the reading is unknown (no movement, dashed grey path). */
  unknown: boolean;
  reversed: boolean;
}

export interface PowerInputs {
  solarW: number | null;
  /** Internal convention (positive = discharging). */
  batteryW: number | null;
  /** Internal convention (positive = importing). */
  gridW: number | null;
  homeW: number | null;
}

function edge(id: FlowId, signedW: number | null, reversible: boolean): FlowEdge {
  if (signedW === null) return { id, magnitudeW: null, idle: false, unknown: true, reversed: false };
  const magnitude = Math.abs(signedW);
  return {
    id,
    magnitudeW: magnitude,
    idle: magnitude < IDLE_THRESHOLD_W,
    unknown: false,
    reversed: reversible && signedW < 0,
  };
}

/** Builds the four flow edges from resolved powers. */
export function buildFlowEdges(p: PowerInputs): FlowEdge[] {
  return [
    edge("solar", p.solarW === null ? null : Math.max(0, p.solarW), false),
    edge("battery", p.batteryW, true),
    edge("grid", p.gridW, true),
    edge("home", p.homeW === null ? null : Math.max(0, p.homeW), false),
  ];
}

/** True when every known flow is idle and at least one flow is known. */
export function siteIsIdle(edges: FlowEdge[]): boolean {
  const known = edges.filter((e) => !e.unknown);
  return known.length > 0 && known.every((e) => e.idle);
}

export type BatteryState = "charging" | "discharging" | "idle" | "unknown";
export type GridState = "importing" | "exporting" | "idle" | "unknown";

export function batteryState(batteryW: number | null): BatteryState {
  if (batteryW === null) return "unknown";
  if (batteryW >= IDLE_THRESHOLD_W) return "discharging";
  if (batteryW <= -IDLE_THRESHOLD_W) return "charging";
  return "idle";
}

export function gridState(gridW: number | null): GridState {
  if (gridW === null) return "unknown";
  if (gridW >= IDLE_THRESHOLD_W) return "importing";
  if (gridW <= -IDLE_THRESHOLD_W) return "exporting";
  return "idle";
}
