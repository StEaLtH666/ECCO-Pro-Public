// Closed-loop battery simulator for the gentle charge controller MODEL (test support; fictional values only, no site data).
//
// A TRUE battery (its own capacity, efficiency and BMS taper, all different from what the controller assumes), SOC reporting with
// rounding, noise and occasional staleness, delivered power that can dip below the setpoint, minute-by-minute real time (a 23 or 25 hour
// day included) and the controller called every re-plan interval. The physics here is written independently of the controller's forward
// model on purpose. Seeded: the same scenario id always gives the same run.
import { planGentle, DEFAULT_GENTLE_PARAMS } from "../../src/gentleController.ts";
import type { GentleDecision, GentleParams, NamedCeiling } from "../../src/gentleController.ts";
import { planGentleCharge } from "../../src/chargePlanner.ts";
import { elapsedMinutes, norm } from "../../src/time.ts";
import type { ClockDay } from "../../src/time.ts";
import { rng } from "../fixtures.ts";

const SPRING: ClockDay = { changeAtMin: 120, deltaMin: 60 };
const AUTUMN: ClockDay = { changeAtMin: 120, deltaMin: -60 };
const ORDINARY: ClockDay = { changeAtMin: 0, deltaMin: 0 };

export interface TrueTaper {
  startSocPct: number;
  endFraction: number;
}
export interface Dip {
  fromMin: number;
  toMin: number;
  /** Delivered power is the setpoint times this (a grid limit or a derating dip). */
  factor: number;
}

export interface Scenario {
  id: number;
  /** "in-band": the true capacity is inside the controller's band; "out-of-band": above it (reported, never asserted). */
  kind: "in-band" | "out-of-band";
  targetSocPct: number;
  bufferMin: number;
  clockDay: ClockDay;
  windowStartMin: number;
  windowWallMin: number;
  windowRealMin: number;
  startSocPct: number;
  nominalKwh: number;
  capacityUpPct: number;
  trueCapacityKwh: number;
  trueEff: number;
  trueTaper: TrueTaper;
  ceilings: NamedCeiling[];
  /** The smallest known ceiling, capped at the editor maximum (what the true battery's acceptance is referenced to). */
  ceilW: number;
  /** Reading: rounding step in percent, noise amplitude in percent (uniform), probability a reading is not refreshed at a tick. */
  readStep: number;
  readNoise: number;
  staleProb: number;
  dips: Dip[];
  replanMin: number;
  paramVariant: "default" | "varied";
  params: Partial<GentleParams>;
  /** A calm scenario: no dips, no stale readings, and a true battery no harsher than the controller's assumptions (taper, efficiency). */
  calm: boolean;
  seed: number;
}

export const trueFraction = (soc: number, t: TrueTaper) => (soc <= t.startSocPct ? 1 : Math.max(t.endFraction, 1 - (1 - t.endFraction) * ((soc - t.startSocPct) / (100 - t.startSocPct))));

export function makeScenario(id: number): Scenario {
  const r = rng(9000 + id);
  const pick = <T>(xs: readonly T[]): T => xs[Math.floor(r() * xs.length)] as T;
  const between = (a: number, b: number) => a + r() * (b - a);
  const targetSocPct = id % 7 === 6 ? pick([60, 70, 95]) : pick([80, 90, 100]);
  const bufferMin = 5 * Math.floor(r() * 25);
  const roll = r();
  const clockDay = roll < 0.7 ? ORDINARY : roll < 0.85 ? SPRING : AUTUMN;
  const windowWallMin = 5 * Math.round(between(180, 600) / 5);
  let windowStartMin: number;
  if (clockDay.deltaMin === 0) windowStartMin = 5 * Math.floor(r() * 288);
  else windowStartMin = norm(clockDay.changeAtMin - 5 * Math.round(between(30, windowWallMin - (clockDay.deltaMin > 0 ? 60 : 30)) / 5));  // a spring window may not end in the skipped hour
  const windowRealMin = elapsedMinutes(windowStartMin, windowWallMin, clockDay);
  const startSocPct = between(5, Math.min(95, targetSocPct - 5));
  const nominalKwh = between(15, 45);
  const capacityUpPct = 6;
  const outOfBand = id % 20 === 18;
  const capErr = outOfBand ? between(capacityUpPct + 2, 12) / 100 : between(-10, capacityUpPct) / 100;
  const calm = id % 5 === 0;
  const trueTaper: TrueTaper = { startSocPct: between(86, 95), endFraction: between(0.08, 0.35) };
  if (calm) trueTaper.startSocPct = Math.max(trueTaper.startSocPct, 90), trueTaper.endFraction = Math.max(trueTaper.endFraction, 0.15);
  const known = pick([[0], [1], [2], [3], [0, 1], [1, 2], [0, 3], [0, 1, 2, 3]]);
  const base = between(3000, 8200);
  const names = ["owner_maximum", "battery_max_charge", "grid_charge_current", "max_grid_charge_power"];
  const ceilings: NamedCeiling[] = names.map((name, k) => ({ name, watts: known.includes(k) ? Math.round(base * (k === known[0] ? 1 : between(1.0, 1.6))) : k % 2 === 0 ? null : undefined }));
  const ceilW = Math.min(8000, Math.min(...ceilings.filter((c) => typeof c.watts === "number").map((c) => c.watts as number)));
  const dips: Dip[] = [];
  if (r() < 0.4 && !calm) {
    const n = 1 + Math.floor(r() * 2);
    for (let k = 0; k < n; k++) {
      const from = Math.round(between(10, Math.max(11, windowRealMin - 40)));
      dips.push({ fromMin: from, toMin: from + Math.round(between(5, 25)), factor: between(0.3, 0.8) });
    }
  }
  const varied = id % 4 === 3;
  const params: Partial<GentleParams> = varied ? { maxChanges: pick([2, 3, 6, 10]), dwellMin: pick([0, 15, 30, 45]), hysteresisW: pick([0, 300, 500, 700]) } : {};
  return {
    id, kind: outOfBand ? "out-of-band" : "in-band", targetSocPct, bufferMin, clockDay, windowStartMin, windowWallMin, windowRealMin, startSocPct, nominalKwh, capacityUpPct,
    trueCapacityKwh: nominalKwh * (1 + capErr), trueEff: calm ? 0.95 + between(0, 0.02) : 0.95 + between(-0.02, 0.02), trueTaper, ceilings, ceilW,
    readStep: pick([1, 1, 0.1]), readNoise: pick([0, 0, 0.2]), staleProb: calm ? 0 : pick([0, 0, 0.1, 0.25]), dips, replanMin: pick([5, 10, 15]),
    paramVariant: varied ? "varied" : "default", params, calm, seed: 31 * id + 7,
  };
}

/** Wall-clock minute of the day at real minute `t` of the window (the controller never sees this; only the window and the elapsed count). */
export function wallAt(sc: Scenario, t: number): number {
  const crossAt = sc.clockDay.deltaMin === 0 ? Infinity : ((sc.clockDay.changeAtMin - sc.windowStartMin + 1440) % 1440);
  return norm(sc.windowStartMin + t + (t >= crossAt ? sc.clockDay.deltaMin : 0));
}

const dipFactor = (sc: Scenario, t: number) => sc.dips.reduce((f, d) => (t >= d.fromMin && t < d.toMin ? Math.min(f, d.factor) : f), 1);

/** Deliver one real minute at `appliedW`: grid-side watts, limited by the true acceptance and any dip. Returns the new true SOC. */
function physics(sc: Scenario, soc: number, appliedW: number, t: number): number {
  const delivered = Math.min(appliedW * dipFactor(sc, t), sc.ceilW * trueFraction(soc, sc.trueTaper));
  return Math.min(100, soc + (((delivered / 1000 / 60) * sc.trueEff) / (sc.trueCapacityKwh / 100)));
}

/** Minutes the TRUE battery needs at a constant setpoint with no dips (null if not within `limit` minutes). */
export function trueFinishMin(sc: Scenario, setpointW: number, from = sc.startSocPct, limit = 3000): number | null {
  let soc = from;
  const plain = { ...sc, dips: [] as Dip[] };
  for (let t = 0; t < limit; t++) {
    if (soc >= sc.targetSocPct - 1e-9) return t;
    soc = physics(plain, soc, setpointW, t);
  }
  return null;
}

export const readTolerance = (sc: Scenario) => sc.readStep / 2 + sc.readNoise;
export const dipLossMin = (sc: Scenario) => sc.dips.reduce((a, d) => a + (1 - d.factor) * (d.toMin - d.fromMin), 0);

export type Feasibility = "infeasible" | "buffer" | "tight" | "margin";
/**
 * What the TRUE battery can do at the full ceiling with no controller in the way: "infeasible" = not even by the window end; "buffer" =
 * only inside the finish-early buffer (after the deadline); "tight" = by the deadline but with less than the margin; "margin" = by the
 * deadline with the dips' lost time plus 10 minutes to spare.
 */
export function feasibility(sc: Scenario): Feasibility {
  const f = trueFinishMin(sc, sc.ceilW);
  const deadline = sc.windowRealMin - sc.bufferMin;
  if (f === null || f > sc.windowRealMin) return "infeasible";
  if (f > deadline) return "buffer";
  return f + dipLossMin(sc) + 10 <= deadline ? "margin" : "tight";
}

export interface TickRecord {
  t: number;
  decision: Omit<GentleDecision, "trajectory">;
  /** The setpoint in force before this tick's decision, the real minutes since the last change, and the budget used before it. */
  appliedBefore: number | null;
  sinceChange: number | null;
  usedBefore: number;
}

export interface ChangeRecord {
  t: number;
  kind: "START" | "INCREASE" | "DECREASE";
  code: string;
  fromW: number | null;
  toW: number;
}

export interface RunResult {
  sc: Scenario;
  deadlineMin: number;
  /** First real minute the true SOC was within the reading tolerance of the target (null: never). */
  reachedTolMin: number | null;
  /** First real minute the true SOC was at least the target (null: never). */
  reachedStrictMin: number | null;
  finalSocPct: number;
  peakW: number;
  ticks: TickRecord[];
  changes: ChangeRecord[];
  firstStatus: string;
}

/** The controller in the loop, an ideal actuator (applies every recommended change at once). */
export function runClosedLoop(sc: Scenario, controller: typeof planGentle = planGentle): RunResult {
  const r = rng(sc.seed);
  const tol = readTolerance(sc);
  const params: Partial<GentleParams> = { replanMin: sc.replanMin, ...sc.params };
  const quant = (x: number) => Math.min(100, Math.max(0, Math.round(x / sc.readStep) * sc.readStep));
  let soc = sc.startSocPct;
  let applied: number | null = null;
  let lastChange: number | null = null;
  let used = 0;
  let reading = quant(soc + sc.readNoise * (2 * r() - 1));
  let readAt = 0;
  let reachedTol: number | null = null;
  let reachedStrict: number | null = null;
  let peak = 0;
  const ticks: TickRecord[] = [];
  const changes: ChangeRecord[] = [];
  let firstStatus = "";
  let done = false;
  for (let t = 0; t <= sc.windowRealMin; t++) {
    if (reachedTol === null && soc >= sc.targetSocPct - tol) reachedTol = t;
    if (reachedStrict === null && soc >= sc.targetSocPct - 1e-9) reachedStrict = t;
    if (t === sc.windowRealMin) break;
    if (t % sc.replanMin === 0 && !done) {
      if (t > 0 && r() >= sc.staleProb) {
        reading = quant(soc + sc.readNoise * (2 * r() - 1));
        readAt = t;
      }
      const d = controller({
        targetSocPct: sc.targetSocPct, bufferMin: sc.bufferMin,
        chargeWindow: { startMin: sc.windowStartMin, endMin: norm(sc.windowStartMin + sc.windowWallMin), clockDay: sc.clockDay },
        elapsedMin: t, socPct: reading, socAgeMin: t - readAt, capacityKwh: sc.nominalKwh, capacityUpPct: sc.capacityUpPct,
        ceilings: sc.ceilings, currentSetpointW: applied, lastChangeElapsedMin: lastChange, changesUsed: used, params,
      });
      const { trajectory: _drop, ...rest } = d;
      ticks.push({ t, decision: rest, appliedBefore: applied, sinceChange: lastChange === null ? null : t - lastChange, usedBefore: used });
      if (firstStatus === "") firstStatus = d.status;
      if (d.status === "NOTHING_TO_CHARGE") {
        applied = 0;
        done = true;
      }
      else if (d.changeRecommended && d.setpointW !== null) {
        changes.push({ t, kind: d.change as "START" | "INCREASE" | "DECREASE", code: d.codes[d.codes.length - 1] as string, fromW: applied, toW: d.setpointW });
        applied = d.setpointW;
        lastChange = t;
        used = d.changesUsed;
      }
      if (applied !== null && applied > peak) peak = applied;
    }
    soc = physics(sc, soc, applied ?? 0, t);
  }
  return { sc, deadlineMin: sc.windowRealMin - sc.bufferMin, reachedTolMin: reachedTol, reachedStrictMin: reachedStrict, finalSocPct: soc, peakW: peak, ticks, changes, firstStatus };
}

/** The static planner's fixed rate in the same simulator (same true battery, same dips; no feedback). */
export function runStatic(sc: Scenario): { rateW: number; reachedTolMin: number | null; status: string } {
  const r = rng(sc.seed);
  const reading = Math.min(100, Math.max(0, Math.round((sc.startSocPct + sc.readNoise * (2 * r() - 1)) / sc.readStep) * sc.readStep));
  const cMax = Math.floor(sc.ceilW / 100) * 100;
  const plan = planGentleCharge({ startSocPct: reading, targetSocPct: sc.targetSocPct, capacityKwh: sc.nominalKwh, capacityUpPct: sc.capacityUpPct, windowMin: sc.windowRealMin, bufferMin: sc.bufferMin, taperMin: 15, maxW: cMax });
  const rate = plan.rateW === null ? (plan.status === "NOTHING_TO_CHARGE" ? 0 : cMax) : Math.min(plan.rateW, cMax);
  const tol = readTolerance(sc);
  let soc = sc.startSocPct;
  for (let t = 0; t <= sc.windowRealMin; t++) {
    if (soc >= sc.targetSocPct - tol) return { rateW: rate, reachedTolMin: t, status: plan.status };
    soc = physics(sc, soc, rate, t);
  }
  return { rateW: rate, reachedTolMin: null, status: plan.status };
}

export { DEFAULT_GENTLE_PARAMS };
