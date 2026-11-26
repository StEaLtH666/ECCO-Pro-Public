// Fictional illustrative values only (no site data).
import { createSettings } from "../src/settings.ts";
import type { PlanSettings, PlanValues } from "../src/settings.ts";
import type { NativeSlot } from "../src/tou.ts";

export const slot = (startMin: number, powerW: number, targetSoc: number, source: "Grid" | "None"): NativeSlot => ({ startMin, powerW, targetSoc, source });

/** A typical table: one overnight grid-charge slot, five idle slots. Idle slots share attributes (they merge). */
export function exampleBaseline(): NativeSlot[] {
  return [
    slot(23 * 60 + 30, 5000, 90, "Grid"),
    slot(5 * 60, 5000, 15, "None"),
    slot(9 * 60, 5000, 15, "None"),
    slot(13 * 60, 5000, 15, "None"),
    slot(16 * 60, 5000, 15, "None"),
    slot(19 * 60, 5000, 15, "None"),
  ];
}

/** Six slots with six distinct targets: nothing merges, so any extra boundary needs an extra slot. */
export function distinctBaseline(): NativeSlot[] {
  return [0, 240, 480, 720, 960, 1200].map((m, i) => slot(m, 5000, 15 + 5 * i, "None"));
}

/** Six starts, identical attributes: the whole day is one behaviour. */
export function quietBaseline(): NativeSlot[] {
  return [0, 240, 480, 720, 960, 1200].map((m) => slot(m, 5000, 15, "None"));
}

export function exampleValues(): PlanValues {
  return {
    "charge.targetSoc": 90,
    "charge.bufferMin": 60,
    "charge.powerW": 5000,
    "charge.windowStartMin": 23 * 60 + 30,
    "charge.windowEndMin": 5 * 60,
    "export.stopSoc": 30,
    "export.powerW": 3000,
    "export.startMin": 19 * 60 + 30,
    "export.durationMin": 120,
    "reserve.backupPct": 40,
    "reserve.planningPct": 50,
  };
}

export function exampleSettings(): PlanSettings {
  return createSettings(exampleValues());
}

/** mulberry32: a small seeded generator so property loops are reproducible. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
