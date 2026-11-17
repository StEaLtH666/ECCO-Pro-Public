// Gentle Smart Charging: READ-ONLY controller MODEL (owner directive 17 Nov 2026). Pure data in, data out: no I/O, no clock, no class.
//
// At each tick it turns the state into a RECOMMENDED charge-power setpoint: the lowest 100 W step whose forward simulation (pessimistic
// capacity, assumed BMS taper) reaches the target by the deadline (window end minus the finish-early buffer), then hysteresis, dwell and
// a changes budget. It never lowers the target, never exceeds a safe ceiling and never recommends from unknown or stale SOC.
//
// NOTHING HERE ACTUATES. Today's firmware fixes the Free Power rate at START, so a recommended CHANGE cannot be applied: an actuator
// (a Free Power rate controller on the Dump V1.1 pattern, with a write budget and live proof) does not exist. The module only says what
// such a controller would do, and labels it "model, not a command".
import { elapsedMinutes, span } from "./time.ts";
import type { ClockDay } from "./time.ts";
import { LIMITS } from "./settings.ts";

export const CONTROLLER_LABEL = "model, not a command";
export const ASSUMED_LABEL = "assumed, not measured";
export const ACTUATION_REASON =
  "Today's firmware fixes the Free Power rate at START and verifies against it; applying a change needs a rate controller that does not exist (it would need a write budget and live proof).";

/** Hard bounds of the numbers the model accepts (the buffer step is the owner's 5-minute grid). */
export const GENTLE_BOUNDS = Object.freeze({ targetMin: 10, targetMax: 100, bufferMin: LIMITS.bufferMin, bufferMax: LIMITS.bufferMax, bufferStep: 5, replanMin: 5, replanMax: 15 });

export type GentleStatus = "OK" | "NOTHING_TO_CHARGE" | "TARGET_AT_RISK" | "TARGET_UNREACHABLE" | "NO_DATA" | "NO_SAFE_CEILING" | "DEADLINE_PASSED" | "INVALID";
export type GentleChange = "NONE" | "START" | "INCREASE" | "DECREASE";

/** A safe power ceiling candidate. `watts` null / undefined / not a finite number >= 0 means UNKNOWN (never guessed). */
export interface NamedCeiling {
  name: string;
  watts: number | null | undefined;
}

/** Battery-side power from a current limit and a voltage (a convenience for the two current-based ceilings); null if either is unknown. */
export function powerFromCurrent(amps: number | null | undefined, volts: number | null | undefined): number | null {
  if (typeof amps !== "number" || typeof volts !== "number" || !Number.isFinite(amps) || !Number.isFinite(volts) || amps < 0 || volts <= 0) return null;
  return amps * volts;
}

export interface GentleParams {
  /** Setpoint granularity (the editor's 100 W step). */
  stepW: number;
  /** Lowest recommendable setpoint (the editor's 500 W). */
  minW: number;
  /** The editor's maximum; an upper bound only, never a substitute for an unknown ceiling. */
  hardMaxW: number;
  /** A decrease is recommended only when it saves at least this much. */
  hysteresisW: number;
  /** Minimum real minutes between two changes (an increase needed for the deadline ignores it). */
  dwellMin: number;
  /** Time-domain hysteresis: a decrease must leave at least this many minutes of slack to the deadline (stops decrease-then-increase flapping). */
  decreaseSlackMin: number;
  /** Re-plan interval the caller should use, 5-15 minutes. */
  replanMin: number;
  /** Maximum setpoint changes per window after the START (the write budget a future actuator would need). */
  maxChanges: number;
  /** SOC readings older than this are stale. */
  maxSocAgeMin: number;
  /** Resolution of the SOC reading in percent points (ASSUMED 1, an integer sensor): the plan starts from the reading minus half of it. */
  socResolutionPct: number;
  /** Grid-side to battery-side efficiency. */
  chargeEff: number;
  /** BMS taper (ASSUMED, not measured): below this SOC the battery accepts the full ceiling. */
  taperStartSocPct: number;
  /** BMS taper (ASSUMED): acceptance at 100 % SOC as a fraction of the ceiling; linear in between. */
  taperEndFraction: number;
  /** Extra minutes reserved after reaching a 100 % target (final taper tail and a hold). Not applied to lower targets. */
  topHoldMin: number;
}

export const DEFAULT_GENTLE_PARAMS: Readonly<GentleParams> = Object.freeze({
  stepW: 100,
  minW: LIMITS.chargePowerMin,
  hardMaxW: LIMITS.chargePowerMax,
  hysteresisW: 500,
  dwellMin: 30,
  decreaseSlackMin: 15,
  replanMin: 10,
  maxChanges: 6,
  maxSocAgeMin: 15,
  socResolutionPct: 1,
  chargeEff: 0.95,
  taperStartSocPct: 90,
  taperEndFraction: 0.15,
  topHoldMin: 20,
});

export interface GentleInput {
  /** 10-100 (100 allowed). Never changed by the model. */
  targetSocPct: number;
  /** Finish-before-window-end buffer, 0-120 minutes in 5-minute steps. */
  bufferMin: number;
  /** The owner's wall-clock window and the clock day it falls on; the real length is worked out with elapsedMinutes. */
  chargeWindow: { startMin: number; endMin: number; clockDay: ClockDay };
  /** Real minutes since the window opened (a monotonic count; not the wall clock). */
  elapsedMin: number;
  /** Current SOC percent, or null when unknown. */
  socPct: number | null;
  /** Age of that reading in real minutes, or null when unknown (treated as stale). */
  socAgeMin: number | null;
  /** Nominal usable capacity in kWh. */
  capacityKwh: number;
  /** The real capacity may be this much higher than nominal (as in the static planner). */
  capacityUpPct: number;
  /** Learned capacity, when there is one; the larger of the two is used for a charge plan. */
  learnedCapacityKwh?: number | null;
  /** The safe power ceilings that are known; the smallest known one applies. */
  ceilings: readonly NamedCeiling[];
  /** The setpoint now in force (null before the START). */
  currentSetpointW: number | null;
  /** Real minutes since window start at the last setpoint change (null if none yet). */
  lastChangeElapsedMin: number | null;
  /** Setpoint changes since the START in this window. */
  changesUsed: number;
  params?: Partial<GentleParams>;
}

export interface ProjectionPoint {
  inMin: number;
  socPct: number;
}

export type GentleCode =
  | "INVALID_INPUT"
  | "NO_SOC"
  | "STALE_SOC"
  | "AT_TARGET"
  | "NO_CEILING"
  | "CEILING_BELOW_MIN"
  | "DEADLINE_PASSED"
  | "BUFFER_AS_LONG_AS_WINDOW"
  | "START"
  | "LOWEST_STEP"
  | "AT_CEILING"
  | "INCREASE_FOR_DEADLINE"
  | "ABOVE_CEILING"
  | "DECREASE_SAVING"
  | "HELD_HYSTERESIS"
  | "HELD_SLACK"
  | "HELD_DWELL"
  | "HELD_BUDGET"
  | "TARGET_AT_RISK"
  | "TARGET_UNREACHABLE"
  | "UNCHANGED";

export interface GentleDecision {
  status: GentleStatus;
  label: typeof CONTROLLER_LABEL;
  /** The BMS taper and the capacity band are assumptions, never measurements. */
  assumptionsLabel: typeof ASSUMED_LABEL;
  reasons: string[];
  codes: GentleCode[];
  /** Echo of the input target: the model never lowers it. */
  targetSocPct: number;
  /** The usable ceiling (smallest known, rounded down to a step and capped at the editor maximum), and which ceiling set it. */
  ceilingW: number | null;
  ceilingName: string | null;
  /** The lowest step that reaches the target by the deadline (null when none up to the ceiling does, or no recommendation). */
  neededW: number | null;
  /** What to hold or apply now, after hysteresis, dwell and the budget. A multiple of the step within [minW, ceiling], or null. */
  setpointW: number | null;
  changeRecommended: boolean;
  change: GentleChange;
  /** Real minutes from now to the deadline / window end (null when not computed). */
  deadlineInMin: number | null;
  windowEndInMin: number | null;
  /** Projection at setpointW (pessimistic capacity, assumed taper): minutes from now to reach the target, margin to the deadline. */
  finishInMin: number | null;
  marginMin: number | null;
  trajectory: ProjectionPoint[];
  /** When the plan is late: the smallest buffer (5-minute steps) that would absorb it at the ceiling, or null. */
  suggestedBufferMin: number | null;
  changesUsed: number;
  changesLeft: number;
  nextReplanInMin: number | null;
  actuationSupported: false;
  actuationReason: string;
}

const MAX_HORIZON_MIN = 2 * 1440;
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const ceilStep = (x: number, step: number) => Math.ceil(x / step - 1e-9) * step;
const floorStep = (x: number, step: number) => Math.floor(x / step + 1e-9) * step;
const round1 = (x: number) => Math.round(x * 10) / 10;

/** The real length of the owner's wall-clock window in minutes (clock-change aware), or null for a zero-length window. */
export function windowRealMinutes(startMin: number, endMin: number, clockDay: ClockDay): number | null {
  if (!isNum(startMin) || !isNum(endMin)) return null;
  const wall = span(startMin, endMin);
  return wall === 0 ? null : elapsedMinutes(startMin, wall, clockDay);
}

/** The smallest KNOWN ceiling (finite, >= 0), or null when none is known. A tie keeps the first name. */
export function smallestKnownCeiling(ceilings: readonly NamedCeiling[]): { watts: number; name: string } | null {
  let best: { watts: number; name: string } | null = null;
  for (const c of ceilings) {
    if (!c || !isNum(c.watts) || c.watts < 0) continue;
    if (best === null || c.watts < best.watts) best = { watts: c.watts, name: String(c.name) };
  }
  return best;
}

/** BMS acceptance power as a fraction of the ceiling at a SOC: 1 up to the taper start, then linear down to `endFraction` at 100 %. */
export function acceptanceFraction(socPct: number, taperStartSocPct: number, endFraction: number): number {
  if (socPct <= taperStartSocPct) return 1;
  const f = 1 - (1 - endFraction) * ((socPct - taperStartSocPct) / (100 - taperStartSocPct));
  return Math.max(f, endFraction);
}

export interface ChargeModel {
  /** Pessimistic capacity in kWh. */
  capacityKwh: number;
  chargeEff: number;
  /** The usable ceiling in W (the taper's reference). */
  ceilingW: number;
  taperStartSocPct: number;
  taperEndFraction: number;
}

/**
 * Forward simulation, one minute at a time, of a charge at a fixed setpoint (grid-side watts): delivered = min(setpoint, ceiling x taper
 * fraction at the SOC). Returns the minutes from now until the target is reached (null if not within maxMin) and sampled points.
 */
export function projectCharge(startSocPct: number, setpointW: number, targetSocPct: number, m: ChargeModel, maxMin: number, sampleEveryMin = 0): { finishMin: number | null; points: ProjectionPoint[] } {
  const points: ProjectionPoint[] = sampleEveryMin > 0 ? [{ inMin: 0, socPct: round1(startSocPct) }] : [];
  if (startSocPct >= targetSocPct - 1e-9) return { finishMin: 0, points };
  const n = Math.min(Math.ceil(maxMin), MAX_HORIZON_MIN);
  let soc = startSocPct;
  for (let i = 1; i <= n; i++) {
    const delivered = Math.min(setpointW, m.ceilingW * acceptanceFraction(soc, m.taperStartSocPct, m.taperEndFraction));
    const gain = ((delivered / 1000 / 60) * m.chargeEff) / (m.capacityKwh / 100);
    if (!(gain > 0)) {
      if (sampleEveryMin > 0 && i % sampleEveryMin === 0) points.push({ inMin: i, socPct: round1(soc) });
      continue;
    }
    if (soc + gain >= targetSocPct - 1e-9) {
      const finish = i - 1 + (targetSocPct - soc) / gain;
      if (sampleEveryMin > 0) points.push({ inMin: round1(finish), socPct: round1(targetSocPct) });
      return { finishMin: finish, points };
    }
    soc += gain;
    if (sampleEveryMin > 0 && i % sampleEveryMin === 0) points.push({ inMin: i, socPct: round1(soc) });
  }
  return { finishMin: null, points };
}

function mergeParams(over: Partial<GentleParams> | undefined): GentleParams {
  const out: GentleParams = { ...DEFAULT_GENTLE_PARAMS };
  if (over) for (const k of Object.keys(DEFAULT_GENTLE_PARAMS) as (keyof GentleParams)[]) if (over[k] !== undefined) out[k] = over[k] as number;
  return out;
}

function paramProblem(p: GentleParams): string | null {
  for (const k of Object.keys(DEFAULT_GENTLE_PARAMS) as (keyof GentleParams)[]) if (!isNum(p[k])) return "Parameter " + k + " is not a number.";
  if (!Number.isInteger(p.stepW) || p.stepW < 1) return "stepW must be a whole number of watts, at least 1.";
  if (p.minW < p.stepW || p.hardMaxW < p.minW) return "minW and hardMaxW are inconsistent (stepW <= minW <= hardMaxW).";
  if (p.hysteresisW < 0 || p.dwellMin < 0 || p.dwellMin > 1440 || p.decreaseSlackMin < 0 || p.decreaseSlackMin > 120) return "hysteresisW, dwellMin or decreaseSlackMin is out of range.";
  if (!Number.isInteger(p.replanMin) || p.replanMin < GENTLE_BOUNDS.replanMin || p.replanMin > GENTLE_BOUNDS.replanMax) return "replanMin must be 5-15 whole minutes.";
  if (!Number.isInteger(p.maxChanges) || p.maxChanges < 0 || p.maxChanges > 100) return "maxChanges must be a whole number 0-100.";
  if (p.maxSocAgeMin <= 0 || p.maxSocAgeMin > 120) return "maxSocAgeMin must be 1-120 minutes.";
  if (p.socResolutionPct < 0 || p.socResolutionPct > 5) return "socResolutionPct must be 0-5.";
  if (p.chargeEff <= 0 || p.chargeEff > 1) return "chargeEff must be above 0 and at most 1.";
  if (p.taperStartSocPct < 0 || p.taperStartSocPct > 99) return "taperStartSocPct must be 0-99.";
  if (p.taperEndFraction <= 0 || p.taperEndFraction > 1) return "taperEndFraction must be above 0 and at most 1.";
  if (p.topHoldMin < 0 || p.topHoldMin > 120) return "topHoldMin must be 0-120 minutes.";
  return null;
}

function inputProblem(i: GentleInput): string | null {
  if (!isNum(i.targetSocPct) || i.targetSocPct < GENTLE_BOUNDS.targetMin || i.targetSocPct > GENTLE_BOUNDS.targetMax) return "The target must be 10-100 %.";
  if (!isNum(i.bufferMin) || i.bufferMin < GENTLE_BOUNDS.bufferMin || i.bufferMin > GENTLE_BOUNDS.bufferMax || i.bufferMin % GENTLE_BOUNDS.bufferStep !== 0) return "The finish buffer must be 0-120 minutes in 5-minute steps.";
  if (!isNum(i.capacityKwh) || i.capacityKwh <= 0) return "The capacity must be a positive number of kWh.";
  if (!isNum(i.capacityUpPct) || i.capacityUpPct < 0) return "The capacity band must be a number of percent, 0 or more.";
  if (i.learnedCapacityKwh !== undefined && i.learnedCapacityKwh !== null && (!isNum(i.learnedCapacityKwh) || i.learnedCapacityKwh <= 0)) return "The learned capacity must be a positive number of kWh or null.";
  if (!isNum(i.elapsedMin) || i.elapsedMin < 0) return "The elapsed minutes must be a number, 0 or more.";
  if (!i.chargeWindow || !isNum(i.chargeWindow.startMin) || !isNum(i.chargeWindow.endMin) || !i.chargeWindow.clockDay) return "The window or the clock day is missing.";
  if (windowRealMinutes(i.chargeWindow.startMin, i.chargeWindow.endMin, i.chargeWindow.clockDay) === null) return "The window has no length.";
  if (!Array.isArray(i.ceilings)) return "The ceilings must be a list.";
  if (i.currentSetpointW !== null && (!isNum(i.currentSetpointW) || i.currentSetpointW < 0)) return "The current setpoint must be a number of watts or null.";
  if (i.lastChangeElapsedMin !== null && (!isNum(i.lastChangeElapsedMin) || i.lastChangeElapsedMin < 0 || i.lastChangeElapsedMin > i.elapsedMin)) return "The last change must be null or between the window start and now.";
  if (!Number.isInteger(i.changesUsed) || i.changesUsed < 0) return "The changes used must be a whole number, 0 or more.";
  return null;
}

function shell(status: GentleStatus, targetSocPct: number, reasons: string[], codes: GentleCode[], p: GentleParams | null, changesUsed: number): GentleDecision {
  return {
    status,
    label: CONTROLLER_LABEL,
    assumptionsLabel: ASSUMED_LABEL,
    reasons,
    codes,
    targetSocPct,
    ceilingW: null,
    ceilingName: null,
    neededW: null,
    setpointW: null,
    changeRecommended: false,
    change: "NONE",
    deadlineInMin: null,
    windowEndInMin: null,
    finishInMin: null,
    marginMin: null,
    trajectory: [],
    suggestedBufferMin: null,
    changesUsed: isNum(changesUsed) ? changesUsed : 0,
    changesLeft: p ? Math.max(0, p.maxChanges - (isNum(changesUsed) ? changesUsed : 0)) : 0,
    nextReplanInMin: p ? p.replanMin : null,
    actuationSupported: false,
    actuationReason: ACTUATION_REASON,
  };
}

interface Choice {
  w: number;
  change: GentleChange;
  code: GentleCode;
  reason: string;
}

/**
 * Hysteresis, dwell, slack and the budget. `target` is the lowest step that makes the deadline (never above cMax), `down` the lowest step
 * that makes it with the decrease slack to spare (what a decrease would go to), `cur` the setpoint in force.
 */
function choose(target: number, down: number, cMax: number, cur: number | null, sinceChange: number, budgetLeft: number, p: GentleParams): Choice {
  if (cur === null || cur <= 0) return { w: target, change: "START", code: "START", reason: "First setpoint: " + target + " W." };
  if (cur > cMax) return { w: target, change: "DECREASE", code: "ABOVE_CEILING", reason: "The setpoint in force (" + cur + " W) is above the safe ceiling (" + cMax + " W): lower it now (safety, not held back by dwell, hysteresis or the budget)." };
  if (target > cur) {
    if (budgetLeft <= 0) return { w: cur, change: "NONE", code: "HELD_BUDGET", reason: "An increase to " + target + " W is needed for the deadline but the changes budget is used up; the setpoint in force is kept and the projection says what that costs." };
    return { w: target, change: "INCREASE", code: "INCREASE_FOR_DEADLINE", reason: "The setpoint in force (" + cur + " W) would finish late: increase to " + target + " W now (never held back by dwell or hysteresis)." };
  }
  if (target < cur) {
    if (down >= cur) return { w: cur, change: "NONE", code: "HELD_SLACK", reason: "The setpoint in force (" + cur + " W) still makes the deadline, but a lower one would leave under " + p.decreaseSlackMin + " min of slack: kept at " + cur + " W." };
    const saving = cur - down;
    if (saving < p.hysteresisW) return { w: cur, change: "NONE", code: "HELD_HYSTERESIS", reason: "A decrease to " + down + " W would save only " + saving + " W, under the " + p.hysteresisW + " W hysteresis: kept at " + cur + " W." };
    if (sinceChange < p.dwellMin) return { w: cur, change: "NONE", code: "HELD_DWELL", reason: "A decrease to " + down + " W is possible but the last change was " + Math.floor(sinceChange) + " min ago, under the " + p.dwellMin + " min dwell: kept at " + cur + " W." };
    if (budgetLeft <= 0) return { w: cur, change: "NONE", code: "HELD_BUDGET", reason: "A decrease to " + down + " W is possible but the changes budget is used up: kept at " + cur + " W." };
    return { w: down, change: "DECREASE", code: "DECREASE_SAVING", reason: "Decrease to " + down + " W: saves " + saving + " W, after the dwell, keeping " + p.decreaseSlackMin + " min of slack to the deadline." };
  }
  return { w: cur, change: "NONE", code: "UNCHANGED", reason: "The setpoint in force (" + cur + " W) is still the lowest step that makes the deadline." };
}

export function planGentle(input: GentleInput): GentleDecision {
  const target = (input && isNum(input.targetSocPct) ? input.targetSocPct : NaN) as number;
  const used = input && isNum(input.changesUsed) ? input.changesUsed : 0;
  const fail = (reason: string, p: GentleParams | null = null) => shell("INVALID", target, [reason + " Nothing is recommended."], ["INVALID_INPUT"], p, used);
  if (!input || typeof input !== "object") return fail("The input is missing.");
  const p = mergeParams(input.params);
  const pp = paramProblem(p);
  if (pp) return fail(pp);
  const ip = inputProblem(input);
  if (ip) return fail(ip, p);

  // Unknown or stale SOC: no recommendation (never a guess).
  if (input.socPct === null || !isNum(input.socPct)) return shell("NO_DATA", target, ["The SOC is unknown; nothing is recommended."], ["NO_SOC"], p, used);
  if (input.socPct < 0 || input.socPct > 100) return shell("NO_DATA", target, ["The SOC reading is not plausible (" + input.socPct + " %); nothing is recommended."], ["NO_SOC"], p, used);
  if (input.socAgeMin === null || !isNum(input.socAgeMin) || input.socAgeMin < 0 || input.socAgeMin > p.maxSocAgeMin) {
    return shell("NO_DATA", target, ["The SOC reading is stale or its age is unknown (limit " + p.maxSocAgeMin + " min); nothing is recommended."], ["STALE_SOC"], p, used);
  }
  const soc = input.socPct;
  if (soc >= target) return shell("NOTHING_TO_CHARGE", target, ["The battery is at " + soc + " %, at or above the " + target + " % target."], ["AT_TARGET"], p, used);

  // The safe ceiling: the smallest KNOWN one, rounded down to a step, capped at the editor maximum. None known = no recommendation.
  const known = smallestKnownCeiling(input.ceilings);
  if (known === null) return shell("NO_SAFE_CEILING", target, ["No safe power ceiling is known (owner maximum, battery maximum charge power, grid-charge power); no default is guessed and nothing is recommended."], ["NO_CEILING"], p, used);
  const cMax = floorStep(Math.min(known.watts, p.hardMaxW), p.stepW);
  const cMin = ceilStep(p.minW, p.stepW);
  if (cMax < cMin) {
    return shell("NO_SAFE_CEILING", target, ["The smallest known ceiling (" + known.name + ", " + Math.round(known.watts) + " W) is below the minimum setpoint of " + cMin + " W; nothing is recommended."], ["CEILING_BELOW_MIN"], p, used);
  }

  // Time: real minutes, clock-change aware (the window length uses elapsedMinutes; elapsed is a monotonic count).
  const windowReal = windowRealMinutes(input.chargeWindow.startMin, input.chargeWindow.endMin, input.chargeWindow.clockDay) as number;
  const toDeadline = windowReal - input.bufferMin - input.elapsedMin;
  const toEnd = windowReal - input.elapsedMin;
  const hold = target >= 100 ? p.topHoldMin : 0;
  const capPess = Math.max(input.capacityKwh, input.learnedCapacityKwh ?? 0) * (1 + input.capacityUpPct / 100);
  const model: ChargeModel = { capacityKwh: capPess, chargeEff: p.chargeEff, ceilingW: cMax, taperStartSocPct: p.taperStartSocPct, taperEndFraction: p.taperEndFraction };
  const sinceChange = input.lastChangeElapsedMin === null ? Infinity : input.elapsedMin - input.lastChangeElapsedMin;
  const budgetLeft = p.maxChanges - used;
  const cur = input.currentSetpointW;

  const out = shell("OK", target, [], [], p, used);
  out.ceilingW = cMax;
  out.ceilingName = known.name;
  out.deadlineInMin = toDeadline;
  out.windowEndInMin = toEnd;

  // Plan from the pessimistic end of the reading's rounding: a reading of 50 may be 49.5.
  const planSoc = Math.max(0, soc - p.socResolutionPct / 2);
  const finish = (w: number, maxMin: number, sample = 0) => projectCharge(planSoc, w, target, model, maxMin, sample);
  const finalise = (c: Choice) => {
    out.setpointW = c.w;
    out.change = c.change;
    out.changeRecommended = c.change !== "NONE";
    out.codes.push(c.code);
    out.reasons.push(c.reason);
    // The START and a safety decrease do not draw on the budget; an ordinary increase or decrease does.
    out.changesUsed = used + (c.change === "INCREASE" || c.code === "DECREASE_SAVING" ? 1 : 0);
    out.changesLeft = Math.max(0, p.maxChanges - out.changesUsed);
    const pr = finish(c.w, Math.max(toEnd - hold, 0), 5);
    out.finishInMin = pr.finishMin === null ? null : round1(pr.finishMin);
    out.marginMin = pr.finishMin === null ? null : round1(toDeadline - hold - pr.finishMin);
    out.trajectory = pr.points;
    return pr;
  };

  if (toDeadline <= 0) {
    out.status = "DEADLINE_PASSED";
    out.codes.push("DEADLINE_PASSED");
    out.reasons.push(input.bufferMin >= windowReal ? "The finish-early buffer (" + input.bufferMin + " min) is as long as the " + windowReal + " min window: the deadline is not after the window opens. The target is not lowered." : "The finish-early deadline has passed with the battery at " + soc + " % (target " + target + " %). The target is not lowered.");
    if (input.bufferMin >= windowReal) out.codes.push("BUFFER_AS_LONG_AS_WINDOW");
    if (toEnd > 0) {
      const c = choose(cMax, cMax, cMax, cur, sinceChange, budgetLeft, p);
      finalise(c);
      out.reasons.push("Time is left before the window ends: the ceiling is the best effort.");
    }
    return out;
  }

  // The lowest step whose forward simulation reaches the target by the deadline (finish time is monotone in the setpoint).
  const avail = toDeadline - hold;
  const lowestStep = (within: number): number | null => {
    if (within <= 0 || finish(cMax, within).finishMin === null) return null;
    let lo = cMin;
    let hi = cMax;
    while (lo < hi) {
      const mid = lo + floorStep((hi - lo) / 2, p.stepW);
      if (finish(mid, within).finishMin !== null) hi = mid;
      else lo = mid + p.stepW;
    }
    return lo;
  };
  const neededW = lowestStep(avail);
  out.neededW = neededW;

  if (neededW === null) {
    // Even the ceiling is late against the deadline: clipped at the ceiling, never a lower target.
    const atCeiling = finish(cMax, Math.max(toEnd - hold, 0)).finishMin;
    const c = choose(cMax, cMax, cMax, cur, sinceChange, budgetLeft, p);
    finalise(c);
    const lateBy = atCeiling === null ? null : atCeiling - avail;
    if (atCeiling !== null) {
      out.status = "TARGET_AT_RISK";
      out.codes.push("TARGET_AT_RISK");
      let b: number | null = null;
      if (lateBy !== null) {
        const nb = input.bufferMin - ceilStep(lateBy, GENTLE_BOUNDS.bufferStep);
        b = nb >= GENTLE_BOUNDS.bufferMin ? nb : null;
      }
      out.suggestedBufferMin = b;
      out.reasons.push("Buffer too small: the target needs more than the safe ceiling of " + cMax + " W (" + known.name + ") to finish by the deadline; at the ceiling it finishes about " + Math.ceil(lateBy as number) + " min late, inside the buffer. The target is not lowered.");
    } else {
      out.status = "TARGET_UNREACHABLE";
      out.codes.push("TARGET_UNREACHABLE");
      out.reasons.push("Buffer too small, or the target is out of reach: even at the safe ceiling of " + cMax + " W (" + known.name + ") the target is not reached before the window ends. The target is not lowered.");
    }
    return out;
  }

  const downW = p.decreaseSlackMin > 0 ? lowestStep(avail - p.decreaseSlackMin) ?? cMax : neededW;
  const c = choose(neededW, downW, cMax, cur, sinceChange, budgetLeft, p);
  const pr = finalise(c);
  if (c.code === "START" || c.code === "INCREASE_FOR_DEADLINE" || c.code === "DECREASE_SAVING" || c.code === "ABOVE_CEILING") {
    out.codes.push(neededW === cMax ? "AT_CEILING" : "LOWEST_STEP");
    out.reasons.push(neededW === cMax ? "The lowest step that makes the deadline is the safe ceiling itself." : "Lowest step whose forward simulation (pessimistic capacity, assumed taper) reaches the target by the deadline.");
  }
  if (pr.finishMin === null || pr.finishMin > avail + 1e-9) {
    // The setpoint in force (kept by dwell, hysteresis or an exhausted budget) would finish late although the ceiling could make it.
    out.status = "TARGET_AT_RISK";
    out.codes.push("TARGET_AT_RISK");
    out.reasons.push("The setpoint that stays in force would finish after the deadline; a higher setpoint is held back by the changes budget. The target is not lowered.");
  }
  return out;
}
