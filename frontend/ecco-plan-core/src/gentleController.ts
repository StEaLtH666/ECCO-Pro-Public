// Gentle Smart Charging: READ-ONLY controller MODEL (owner directive 17 and 18 Nov 2026). Pure data in, data out: no I/O, no clock, no class.
//
// At each tick it turns the state into a RECOMMENDED charge-power setpoint: the lowest 100 W step whose forward simulation (pessimistic
// capacity, assumed BMS taper) reaches the target by the deadline (window end minus the finish-early buffer), then hysteresis, dwell, a
// slew limit and a changes budget. It never lowers the target, never exceeds a safe limit and never recommends from unknown or stale SOC.
// Optional household inputs (demand, solar, a KNOWN safe grid import limit) cap the setpoint by the grid headroom, pessimistically.
//
// NOTHING HERE ACTUATES. Today's firmware fixes the Free Power rate at START, so a recommended CHANGE cannot be applied: an actuator
// (a Free Power rate controller on the Dump V1.1 pattern, with a write budget and live proof) does not exist. The module only says what
// such a controller would do, and labels it "model, not a command". It NEVER guarantees the target (guarantee is always NONE).
import { elapsedMinutes, span } from "./time.ts";
import type { ClockDay } from "./time.ts";
import { LIMITS } from "./settings.ts";

export const CONTROLLER_LABEL = "model, not a command";
export const ASSUMED_LABEL = "assumed, not measured";
export const ACTUATION_REASON =
  "Today's firmware fixes the Free Power rate at START and verifies against it; applying a change needs a rate controller that does not exist (it would need a write budget and live proof).";
export const NO_GUARANTEE_NOTE =
  "The target is NOT guaranteed. This is a plan from assumed battery behaviour, forecasts and the latest readings, not a promise: 100 percent cannot be reached at a fixed rate because the BMS tapers the charge near full and handles the top of charge itself, and a lost reading, a demand spike or a lower real limit can make it miss. The model is read-only: it recommends and applies nothing.";
/** The default finish-early buffer in minutes (the owner's setting; the 0-120 grid in 5-minute steps is unchanged). Used by helpers and tests. */
export const GENTLE_DEFAULT_BUFFER_MIN = 60;

/** Hard bounds of the numbers the model accepts (the buffer step is the owner's 5-minute grid). */
export const GENTLE_BOUNDS = Object.freeze({ targetMin: 10, targetMax: 100, bufferMin: LIMITS.bufferMin, bufferMax: LIMITS.bufferMax, bufferStep: 5, replanMin: 5, replanMax: 15 });

export type GentleStatus = "OK" | "NOTHING_TO_CHARGE" | "TARGET_AT_RISK" | "TARGET_UNREACHABLE" | "NO_DATA" | "NO_SAFE_CEILING" | "DEADLINE_PASSED" | "INVALID";
export type GentleChange = "NONE" | "START" | "INCREASE" | "DECREASE";
export type FallbackPolicy = "KEEP_CURRENT" | "USE_STATIC_PLAN" | "NONE";
export type UnknownDemandPolicy = "ASSUME_PROVISIONAL" | "FALLBACK";
export type ParamKind = "PROVISIONAL" | "OWNER_SET" | "MEASURED_REQUIRED";

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
  /** A decrease is recommended only when it saves at least this much (also the least rise when a recovering grid headroom is followed). */
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
  /** Household demand safety margin on top of the peak, percent (PROVISIONAL). */
  demandMarginPct: number;
  /** Conservative demand in W used when the demand over the window is not covered and the policy is ASSUME_PROVISIONAL (PROVISIONAL, unmeasured). */
  assumedDemandW: number;
  /** Household demand and solar readings older than this are stale (treated as unknown). */
  maxHouseholdAgeMin: number;
  /** Slew limit: a decrease goes down by at most this much per change. At or above hardMaxW it never binds (the v1 behaviour). An increase needed for the deadline may exceed it (JUMP_FOR_DEADLINE). */
  maxDecreaseStepW: number;
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
  demandMarginPct: 20,
  assumedDemandW: 2000,
  maxHouseholdAgeMin: 15,
  maxDecreaseStepW: LIMITS.chargePowerMax,
});

/** The provisional gentle profile a caller may spread over the defaults: the slew is OFF by default so the v1 behaviour is unchanged. */
export const GENTLE_RECOMMENDED_PARAMS: Readonly<Partial<GentleParams>> = Object.freeze({ maxDecreaseStepW: 1000 });

export interface GentlePolicy {
  /** What to hold when the controller cannot run (unknown or stale SOC, unknown ceiling, unusable household input). */
  fallbackPolicy: FallbackPolicy;
  /** What to do when the household demand over the window is not covered by a fresh reading and a forecast. */
  unknownDemandPolicy: UnknownDemandPolicy;
}

export const DEFAULT_GENTLE_POLICY: Readonly<GentlePolicy> = Object.freeze({ fallbackPolicy: "KEEP_CURRENT", unknownDemandPolicy: "ASSUME_PROVISIONAL" });

export interface ParamProvenance {
  kind: ParamKind;
  value: number | string;
  /** What would replace a provisional value: the measurement or decision that settles it. */
  replacedBy: string;
}

const KINDS: Record<string, readonly [ParamKind, string]> = {
  stepW: ["OWNER_SET", "the editor's setpoint step"],
  minW: ["OWNER_SET", "the editor's minimum charge power"],
  hardMaxW: ["OWNER_SET", "the editor's maximum charge power"],
  hysteresisW: ["PROVISIONAL", "the owner's confirmation after watching real nights"],
  dwellMin: ["PROVISIONAL", "the owner's confirmation and the actuator's settle time"],
  decreaseSlackMin: ["PROVISIONAL", "the owner's confirmation after watching real nights"],
  replanMin: ["PROVISIONAL", "the owner's confirmation and the actuator's cadence"],
  maxChanges: ["PROVISIONAL", "the write budget of a proven actuator"],
  maxSocAgeMin: ["PROVISIONAL", "the real update rate of the SOC sensor"],
  socResolutionPct: ["PROVISIONAL", "the real resolution of the SOC sensor"],
  chargeEff: ["PROVISIONAL", "the measured grid-to-battery energy ratio over several nights"],
  taperStartSocPct: ["MEASURED_REQUIRED", "the BMS taper curve measured over several full charges"],
  taperEndFraction: ["MEASURED_REQUIRED", "the BMS taper curve measured over several full charges"],
  topHoldMin: ["MEASURED_REQUIRED", "the measured time from the last taper step to the BMS finishing the top of charge"],
  demandMarginPct: ["PROVISIONAL", "the measured spread of real demand against its forecast"],
  assumedDemandW: ["MEASURED_REQUIRED", "the measured overnight household demand profile (unknown today)"],
  maxHouseholdAgeMin: ["PROVISIONAL", "the real update rate of the demand and solar sensors"],
  maxDecreaseStepW: ["PROVISIONAL", "the owner's confirmation (recommended 1000 W; off by default)"],
  fallbackPolicy: ["PROVISIONAL", "the owner's choice"],
  unknownDemandPolicy: ["PROVISIONAL", "the owner's choice"],
  targetSocPct: ["OWNER_SET", "the owner's charge target"],
  bufferMin: ["OWNER_SET", "the owner's finish-early buffer"],
  gridImportLimitW: ["OWNER_SET", "the owner's or installer's safe grid import limit (unknown means no headroom constraint)"],
};

function buildProvenance(): Readonly<Record<string, Readonly<ParamProvenance>>> {
  const out: Record<string, Readonly<ParamProvenance>> = {};
  const values: Record<string, number | string> = { ...DEFAULT_GENTLE_PARAMS, ...DEFAULT_GENTLE_POLICY, targetSocPct: "owner setting", bufferMin: GENTLE_DEFAULT_BUFFER_MIN, gridImportLimitW: "owner setting or unknown" };
  for (const name of Object.keys(KINDS)) {
    const k = KINDS[name] as readonly [ParamKind, string];
    out[name] = Object.freeze({ kind: k[0], value: values[name] as number | string, replacedBy: k[1] });
  }
  return Object.freeze(out);
}

/** Where every parameter value comes from: PROVISIONAL (a generic conservative default, not measured), OWNER_SET, or MEASURED_REQUIRED (unknown today). */
export const PARAM_PROVENANCE: Readonly<Record<string, Readonly<ParamProvenance>>> = buildProvenance();

/** A step profile: `watts` applies from `fromInMin` minutes from now until the next point (the last one holds to the end). */
export interface StepPoint {
  fromInMin: number;
  watts: number;
}

/** Optional household inputs. Demand EXCLUDES the battery charger itself (the caller subtracts the present charge draw from a meter reading). */
export interface HouseholdInput {
  /** Household demand now in W, or null when unknown. */
  demandNowW?: number | null;
  /** Age of that reading in real minutes; null or missing counts as stale. */
  demandAgeMin?: number | null;
  /** Forecast demand over the remaining window. The plan uses its PEAK. */
  demandProfile?: readonly StepPoint[] | null;
  /** Available solar now in W, or null when unknown. */
  solarNowW?: number | null;
  solarAgeMin?: number | null;
  /** Forecast solar over the remaining window; counted only with a fresh reading, bounded by the reading and scaled by the confidence. */
  solarProfile?: readonly StepPoint[] | null;
  /** 0..1; missing or invalid counts as 0 (solar not counted). */
  solarConfidence?: number | null;
  /** A KNOWN safe grid import limit in W. null or missing means unknown: no grid-headroom constraint is applied and the reason says so; it is never guessed. */
  gridImportLimitW?: number | null;
}

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
  /** Household demand, solar and the safe grid import limit. Without it the v1 behaviour is unchanged, bit for bit. */
  household?: HouseholdInput;
  policy?: Partial<GentlePolicy>;
  /** The fixed rate the static planner chose at window start (for the USE_STATIC_PLAN fallback). */
  staticPlanRateW?: number | null;
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
  | "UNCHANGED"
  | "NO_GRID_LIMIT"
  | "ASSUMED_DEMAND"
  | "SOLAR_IGNORED"
  | "HOUSEHOLD_UNUSABLE"
  | "HOUSEHOLD_INVALID"
  | "HEADROOM_BELOW_MIN"
  | "HEADROOM_LIMITED"
  | "ABOVE_HEADROOM"
  | "SLEW_LIMITED"
  | "JUMP_FOR_DEADLINE";

export interface FallbackInfo {
  /** True when the controller could not run its normal plan and the fallback policy was consulted (the status says why). */
  applied: boolean;
  policy: FallbackPolicy;
  /** What the policy would hold (a fallback, never a normal plan; the normal setpointW stays null). null = no recommendation. */
  setpointW: number | null;
  reason: string;
}

export interface ProvisionalUse {
  name: string;
  value: number | string;
  kind: ParamKind;
  /** DEFAULT: the generic provisional value; CALLER: the caller set it (its provenance is then the caller's). */
  source: "DEFAULT" | "CALLER";
}

export interface HouseholdReport {
  /** The known grid import limit, or null (then no headroom constraint was applied). */
  gridLimitW: number | null;
  demandBasis: "FORECAST" | "ASSUMED" | "NONE";
  /** The demand peak over the remaining window including the margin (W), or null. */
  demandPeakW: number | null;
  /** The least solar counted over the remaining window (W), or null. */
  solarCountedMinW: number | null;
  /** The pessimistic grid import at the recommended setpoint: setpoint + demand peak - least solar counted (W), or null. */
  projectedImportW: number | null;
  note: string;
}

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
  /** The lowest step that reaches the target by the deadline (null when none up to the safe maximum does, or no recommendation). */
  neededW: number | null;
  /** What to hold or apply now, after hysteresis, dwell, slew and the budget. A multiple of the step within [minW, safe maximum], or null. */
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
  /** When the plan is late: the smallest buffer (5-minute steps) that would absorb it at the safe maximum, or null. */
  suggestedBufferMin: number | null;
  changesUsed: number;
  changesLeft: number;
  nextReplanInMin: number | null;
  actuationSupported: false;
  actuationReason: string;
  /** The target is never guaranteed, in any status. */
  guarantee: "NONE";
  guaranteeNote: string;
  /** The parameters of a provisional or measured-required kind that shaped this decision. */
  provisionalInUse: ProvisionalUse[];
  fallback: FallbackInfo;
  /** The household evaluation; null when no household input was given. */
  household: HouseholdReport | null;
  /** The cap the grid headroom puts on the setpoint (rounded down to a step), or null when no grid limit applies. */
  headroomCapW: number | null;
  /** Which limit sets the highest safe setpoint: the ceiling, the grid headroom, or NONE when no recommendation is made. */
  limitedBy: "NONE" | "CEILING" | "GRID_HEADROOM";
  /** True when an increase needed for the deadline is larger than the slew limit (JUMP_FOR_DEADLINE). */
  jumpForDeadline: boolean;
}

const MAX_HORIZON_MIN = 2 * 1440;
const MAX_PROFILE_POINTS = 1000;
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

/** Grid import in W for a battery-side charge power: charge / efficiency + household demand - solar used. */
export function gridImportW(batteryChargeW: number, chargeEff: number, demandW: number, solarUsedW: number): number {
  return batteryChargeW / chargeEff + demandW - solarUsedW;
}

/** The battery-side charge power the grid allows: efficiency x (grid limit - demand + solar used), never below zero. */
export function batteryHeadroomW(gridLimitW: number, demandW: number, solarUsedW: number, chargeEff: number): number {
  return Math.max(0, chargeEff * (gridLimitW - demandW + solarUsedW));
}

/** The value of a step profile at minute t (the last point at or before t), or null before its first point. */
export function stepProfileAt(profile: readonly StepPoint[], t: number): number | null {
  let v: number | null = null;
  for (const e of profile) {
    if (e.fromInMin <= t) v = e.watts;
    else break;
  }
  return v;
}

/** Why a step profile is unusable (not a list, a bad number, not strictly increasing), or null when it is usable. */
export function stepProfileProblem(profile: unknown): string | null {
  if (!Array.isArray(profile)) return "it is not a list";
  if (profile.length > MAX_PROFILE_POINTS) return "it has more than " + MAX_PROFILE_POINTS + " points";
  let prev = -1;
  for (const e of profile as unknown[]) {
    const pt = e as StepPoint | null;
    if (!pt || typeof pt !== "object" || !isNum(pt.fromInMin) || !isNum(pt.watts) || pt.fromInMin < 0 || pt.watts < 0) return "a point is not a minute and a number of watts, both 0 or more";
    if (pt.fromInMin <= prev) return "the minutes are not strictly increasing";
    prev = pt.fromInMin;
  }
  return null;
}

export interface ChargeModel {
  /** Pessimistic capacity in kWh. */
  capacityKwh: number;
  chargeEff: number;
  /** The usable ceiling in W (the taper's reference). */
  ceilingW: number;
  taperStartSocPct: number;
  taperEndFraction: number;
  /** Optional grid headroom per minute from now, in setpoint (grid-side) watts; the last value holds. A grid limit that is unknown leaves this out. */
  headroomW?: readonly number[];
  /** Optional lead: for the first `leadMin` minutes the setpoint is `leadW` instead of the one given (a raise that waits out the dwell). */
  leadW?: number;
  leadMin?: number;
}

/**
 * Forward simulation, one minute at a time, of a charge at a fixed setpoint (grid-side watts): delivered = min(setpoint, ceiling x taper
 * fraction at the SOC, grid headroom at that minute; an optional lead setpoint covers the first minutes). Returns the minutes from now until the target is reached (null if not within maxMin) and sampled points.
 */
export function projectCharge(startSocPct: number, setpointW: number, targetSocPct: number, m: ChargeModel, maxMin: number, sampleEveryMin = 0): { finishMin: number | null; points: ProjectionPoint[] } {
  const points: ProjectionPoint[] = sampleEveryMin > 0 ? [{ inMin: 0, socPct: round1(startSocPct) }] : [];
  if (startSocPct >= targetSocPct - 1e-9) return { finishMin: 0, points };
  const n = Math.min(Math.ceil(maxMin), MAX_HORIZON_MIN);
  let soc = startSocPct;
  for (let i = 1; i <= n; i++) {
    const sp = m.leadW !== undefined && m.leadMin !== undefined && i <= m.leadMin ? m.leadW : setpointW;
    let delivered = Math.min(sp, m.ceilingW * acceptanceFraction(soc, m.taperStartSocPct, m.taperEndFraction));
    if (m.headroomW !== undefined) delivered = Math.min(delivered, m.headroomW[Math.min(i - 1, m.headroomW.length - 1)] ?? 0);
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

function mergePolicy(over: Partial<GentlePolicy> | undefined): GentlePolicy {
  const out: GentlePolicy = { ...DEFAULT_GENTLE_POLICY };
  if (over && typeof over === "object") {
    if (over.fallbackPolicy !== undefined) out.fallbackPolicy = over.fallbackPolicy;
    if (over.unknownDemandPolicy !== undefined) out.unknownDemandPolicy = over.unknownDemandPolicy;
  }
  return out;
}

function policyProblem(pol: GentlePolicy): string | null {
  if (pol.fallbackPolicy !== "KEEP_CURRENT" && pol.fallbackPolicy !== "USE_STATIC_PLAN" && pol.fallbackPolicy !== "NONE") return "fallbackPolicy must be KEEP_CURRENT, USE_STATIC_PLAN or NONE.";
  if (pol.unknownDemandPolicy !== "ASSUME_PROVISIONAL" && pol.unknownDemandPolicy !== "FALLBACK") return "unknownDemandPolicy must be ASSUME_PROVISIONAL or FALLBACK.";
  return null;
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
  if (p.demandMarginPct < 0 || p.demandMarginPct > 200) return "demandMarginPct must be 0-200.";
  if (p.assumedDemandW < 0 || p.assumedDemandW > 100000) return "assumedDemandW must be 0-100000 W.";
  if (p.maxHouseholdAgeMin <= 0 || p.maxHouseholdAgeMin > 120) return "maxHouseholdAgeMin must be 1-120 minutes.";
  if (p.maxDecreaseStepW < p.stepW) return "maxDecreaseStepW must be at least one step.";
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

const emptyFallback = (policy: FallbackPolicy): FallbackInfo => ({ applied: false, policy, setpointW: null, reason: "" });

function shell(status: GentleStatus, targetSocPct: number, reasons: string[], codes: GentleCode[], p: GentleParams | null, changesUsed: number, policy: FallbackPolicy = DEFAULT_GENTLE_POLICY.fallbackPolicy): GentleDecision {
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
    guarantee: "NONE",
    guaranteeNote: NO_GUARANTEE_NOTE,
    provisionalInUse: [],
    fallback: emptyFallback(policy),
    household: null,
    headroomCapW: null,
    limitedBy: "NONE",
    jumpForDeadline: false,
  };
}

/** The listed parameters whose kind is not OWNER_SET, with the value in force and where it came from. */
function provisionalList(names: readonly string[], p: GentleParams, pol: GentlePolicy, input: GentleInput): ProvisionalUse[] {
  const out: ProvisionalUse[] = [];
  const pv = p as unknown as Record<string, number>;
  const polv = pol as unknown as Record<string, string>;
  const overP = (input.params ?? {}) as unknown as Record<string, unknown>;
  const overPol = (input.policy ?? {}) as unknown as Record<string, unknown>;
  for (const name of names) {
    const prov = PARAM_PROVENANCE[name];
    if (!prov || prov.kind === "OWNER_SET") continue;
    const isPolicy = name in DEFAULT_GENTLE_POLICY;
    const value = isPolicy ? (polv[name] as string) : (pv[name] as number);
    const over = isPolicy ? overPol[name] : overP[name];
    out.push({ name, value, kind: prov.kind, source: over === undefined ? "DEFAULT" : "CALLER" });
  }
  return out;
}

const CORE_NAMES = ["hysteresisW", "dwellMin", "decreaseSlackMin", "replanMin", "maxChanges", "maxSocAgeMin", "socResolutionPct", "chargeEff", "taperStartSocPct", "taperEndFraction"] as const;

interface HouseholdEval {
  given: boolean;
  /** The known grid import limit, or null. */
  limitW: number | null;
  /** Set when a known limit cannot be checked because the household input is unusable (never a guess). */
  problem: string | null;
  codes: GentleCode[];
  reasons: string[];
  basis: "FORECAST" | "ASSUMED" | "NONE";
  /** The demand peak incl. the margin. */
  peakW: number | null;
  solarMinW: number | null;
  /** The smallest per-minute headroom in setpoint watts, before rounding to a step. */
  capW: number | null;
  perMinW: number[] | null;
}

function noHousehold(): HouseholdEval {
  return { given: false, limitW: null, problem: null, codes: [], reasons: [], basis: "NONE", peakW: null, solarMinW: null, capW: null, perMinW: null };
}

function fresh(age: unknown, maxAge: number): boolean {
  return isNum(age) && age >= 0 && age <= maxAge;
}

/**
 * The pessimistic household evaluation over the remaining horizon: demand = the PEAK of the fresh reading and the forecast profile plus the margin
 * (an unknown demand follows the policy), solar = min(fresh reading, forecast x confidence) per minute (unknown solar counts as 0), the grid limit
 * = a KNOWN limit only. The per-minute headroom in setpoint watts is the battery-side headroom divided back by the efficiency; its least value is the cap.
 */
function evalHousehold(h: HouseholdInput | undefined | null, p: GentleParams, pol: GentlePolicy, horizonMin: number): HouseholdEval {
  if (h === undefined || h === null) return noHousehold();
  const ev = noHousehold();
  ev.given = true;
  const bad = (code: GentleCode, why: string): HouseholdEval => {
    ev.codes.push(code);
    ev.problem = why;
    return ev;
  };
  if (typeof h !== "object") return bad("HOUSEHOLD_INVALID", "The household input is not an object.");
  const lim = h.gridImportLimitW;
  if (lim === undefined || lim === null) {
    ev.codes.push("NO_GRID_LIMIT");
    ev.reasons.push("No safe grid import limit is known: no grid-headroom constraint is applied (nothing is guessed), so household demand and solar are not used.");
    return ev;
  }
  if (!isNum(lim) || lim < 0) return bad("HOUSEHOLD_INVALID", "The grid import limit is not a number of watts, 0 or more.");
  ev.limitW = lim;
  const n = Math.max(1, Math.min(Math.ceil(horizonMin), MAX_HORIZON_MIN));

  // demand: the peak of a fresh reading and the forecast, with the margin
  let nowKnown = false;
  let nowW = 0;
  const dn = h.demandNowW;
  if (dn !== undefined && dn !== null) {
    if (!isNum(dn) || dn < 0) return bad("HOUSEHOLD_INVALID", "The household demand now is not a number of watts, 0 or more.");
    if (fresh(h.demandAgeMin, p.maxHouseholdAgeMin)) {
      nowKnown = true;
      nowW = dn;
    }
  }
  let prof: readonly StepPoint[] | null = null;
  const dp = h.demandProfile;
  if (dp !== undefined && dp !== null) {
    const why = stepProfileProblem(dp);
    if (why !== null) return bad("HOUSEHOLD_INVALID", "The demand profile is not usable: " + why + ".");
    if (dp.length > 0) prof = dp;
  }
  const covered = prof !== null && (nowKnown || (prof[0] as StepPoint).fromInMin === 0);
  let peak = nowKnown ? nowW : 0;
  if (prof !== null) for (const e of prof) if (e.fromInMin < n && e.watts > peak) peak = e.watts;
  if (covered) ev.basis = "FORECAST";
  else if (pol.unknownDemandPolicy === "ASSUME_PROVISIONAL") {
    if (p.assumedDemandW > peak) peak = p.assumedDemandW;
    ev.basis = "ASSUMED";
    ev.codes.push("ASSUMED_DEMAND");
    ev.reasons.push("Household demand over the window is not covered by a fresh reading and a forecast: the provisional assumed demand of " + p.assumedDemandW + " W (assumed, not measured) is the floor of the demand peak.");
  } else {
    ev.codes.push("HOUSEHOLD_UNUSABLE");
    ev.problem = "Household demand over the window is not covered by a fresh reading and a forecast (policy FALLBACK).";
    return ev;
  }
  const peakW = peak * (1 + p.demandMarginPct / 100);
  ev.peakW = peakW;

  // solar: counted only with a fresh reading, a forecast and a confidence; bounded by the reading and the scaled forecast; else 0
  let solarNow = 0;
  let solarKnown = false;
  let solarProf: readonly StepPoint[] | null = null;
  let conf = 0;
  let ignored = false;
  const sn = h.solarNowW;
  if (sn !== undefined && sn !== null) {
    if (isNum(sn) && sn >= 0 && fresh(h.solarAgeMin, p.maxHouseholdAgeMin)) {
      solarNow = sn;
      solarKnown = true;
    } else ignored = true;
  }
  const sp = h.solarProfile;
  if (sp !== undefined && sp !== null && sp.length !== 0) {
    if (stepProfileProblem(sp) === null) solarProf = sp;
    else ignored = true;
  }
  const sc = h.solarConfidence;
  if (sc !== undefined && sc !== null) {
    if (isNum(sc) && sc >= 0 && sc <= 1) conf = sc;
    else ignored = true;
  }
  if (ignored) {
    ev.codes.push("SOLAR_IGNORED");
    ev.reasons.push("A solar input is stale or not usable: solar that cannot be trusted is counted as 0.");
  }
  const counted = solarKnown && solarProf !== null && conf > 0;
  const per: number[] = [];
  let cap = Infinity;
  let solarMin = Infinity;
  for (let t = 0; t < n; t++) {
    const fc = counted ? stepProfileAt(solarProf as readonly StepPoint[], t) : null;
    const s = counted ? Math.min(solarNow, (fc ?? 0) * conf) : 0;
    const hr = batteryHeadroomW(lim, peakW, s, p.chargeEff) / p.chargeEff;
    per.push(hr);
    if (hr < cap) cap = hr;
    if (s < solarMin) solarMin = s;
  }
  ev.perMinW = per;
  ev.capW = cap;
  ev.solarMinW = solarMin;
  return ev;
}

interface Choice {
  w: number;
  change: GentleChange;
  code: GentleCode;
  reason: string;
  extra?: GentleCode[];
  /** A hold that waits out the dwell: the projection assumes a raise to the safe maximum after `min` minutes. */
  lead?: { w: number; min: number };
}

interface ChooseCtx {
  /** The safe ceiling alone (before any grid-headroom cap). */
  ceilW: number;
  /** True when the grid headroom is the binding limit and the target is that cap (a recovering cap, not a deadline need). */
  recovery: boolean;
  /** True when the grid headroom (not the ceiling) sets the safe maximum. */
  headroomBinds: boolean;
  /** With household inputs: does the deadline still hold, with the decrease slack to spare, if a raise waits `remMin` minutes? Undefined without them (the v1 rule: never wait). */
  canWait?: (remMin: number) => boolean;
}

/**
 * Hysteresis, dwell, slack, slew and the budget. `target` is the lowest step that makes the deadline (never above cMax), `down` the lowest step
 * that makes it with the decrease slack to spare (what a decrease would go to), `cur` the setpoint in force.
 */
function choose(target: number, down: number, cMax: number, cur: number | null, sinceChange: number, budgetLeft: number, p: GentleParams, ctx: ChooseCtx): Choice {
  if (cur === null || cur <= 0) return { w: target, change: "START", code: "START", reason: "First setpoint: " + target + " W." };
  if (cur > cMax) {
    const ceilingLimit = cur > ctx.ceilW || !ctx.headroomBinds;
    return {
      w: target,
      change: "DECREASE",
      code: ceilingLimit ? "ABOVE_CEILING" : "ABOVE_HEADROOM",
      reason: ceilingLimit
        ? "The setpoint in force (" + cur + " W) is above the safe ceiling (" + ctx.ceilW + " W): lower it now (safety, not held back by dwell, hysteresis or the budget)."
        : "The setpoint in force (" + cur + " W) is above the safe grid headroom (" + cMax + " W): lower it now (safety, not held back by dwell, hysteresis, slew or the budget).",
    };
  }
  if (target > cur) {
    if (budgetLeft <= 0) return { w: cur, change: "NONE", code: "HELD_BUDGET", reason: "An increase to " + target + " W is needed for the deadline but the changes budget is used up; the setpoint in force is kept and the projection says what that costs." };
    if (ctx.recovery) {
      // The highest safe setpoint fell and is recovering: following it back up is not a deadline need (the deadline is already at risk), so it waits like a saving does.
      if (target - cur < p.hysteresisW) return { w: cur, change: "NONE", code: "HELD_HYSTERESIS", reason: "The highest safe setpoint is " + target + " W, only " + (target - cur) + " W above the setpoint in force, under the " + p.hysteresisW + " W hysteresis: kept at " + cur + " W." };
      if (sinceChange < p.dwellMin) return { w: cur, change: "NONE", code: "HELD_DWELL", reason: "The highest safe setpoint is " + target + " W but the last change was " + Math.floor(sinceChange) + " min ago, under the " + p.dwellMin + " min dwell: kept at " + cur + " W (no flapping on noisy inputs)." };
    }
    if (ctx.canWait !== undefined && sinceChange < p.dwellMin && ctx.canWait(p.dwellMin - sinceChange)) {
      const rem = p.dwellMin - sinceChange;
      return { w: cur, change: "NONE", code: "HELD_DWELL", reason: "An increase to " + target + " W is wanted but the last change was " + Math.floor(sinceChange) + " min ago, under the " + p.dwellMin + " min dwell, and the deadline still holds with " + p.decreaseSlackMin + " min of slack if the raise waits for it: kept at " + cur + " W (no flapping on noisy inputs; the projection assumes a raise after the dwell).", lead: { w: cur, min: Math.ceil(rem) } };
    }
    const jump = target - cur > p.maxDecreaseStepW;
    return {
      w: target,
      change: "INCREASE",
      code: "INCREASE_FOR_DEADLINE",
      reason: "The setpoint in force (" + cur + " W) would finish late: increase to " + target + " W now (never held back by dwell or hysteresis)." + (jump ? " This is a jump of " + (target - cur) + " W, over the " + p.maxDecreaseStepW + " W slew limit, taken because the deadline needs it." : ""),
      extra: jump ? ["JUMP_FOR_DEADLINE"] : undefined,
    };
  }
  if (target < cur) {
    if (down >= cur) return { w: cur, change: "NONE", code: "HELD_SLACK", reason: "The setpoint in force (" + cur + " W) still makes the deadline, but a lower one would leave under " + p.decreaseSlackMin + " min of slack: kept at " + cur + " W." };
    const saving = cur - down;
    if (saving < p.hysteresisW) return { w: cur, change: "NONE", code: "HELD_HYSTERESIS", reason: "A decrease to " + down + " W would save only " + saving + " W, under the " + p.hysteresisW + " W hysteresis: kept at " + cur + " W." };
    if (sinceChange < p.dwellMin) return { w: cur, change: "NONE", code: "HELD_DWELL", reason: "A decrease to " + down + " W is possible but the last change was " + Math.floor(sinceChange) + " min ago, under the " + p.dwellMin + " min dwell: kept at " + cur + " W." };
    if (budgetLeft <= 0) return { w: cur, change: "NONE", code: "HELD_BUDGET", reason: "A decrease to " + down + " W is possible but the changes budget is used up: kept at " + cur + " W." };
    if (cur - down > p.maxDecreaseStepW) {
      const w = Math.max(down, ceilStep(cur - p.maxDecreaseStepW, p.stepW));
      return { w, change: "DECREASE", code: "DECREASE_SAVING", reason: "Decrease to " + w + " W, at most " + p.maxDecreaseStepW + " W per change (the plan allows " + down + " W): saves " + (cur - w) + " W, after the dwell, keeping " + p.decreaseSlackMin + " min of slack to the deadline.", extra: ["SLEW_LIMITED"] };
    }
    return { w: down, change: "DECREASE", code: "DECREASE_SAVING", reason: "Decrease to " + down + " W: saves " + saving + " W, after the dwell, keeping " + p.decreaseSlackMin + " min of slack to the deadline." };
  }
  return { w: cur, change: "NONE", code: "UNCHANGED", reason: "The setpoint in force (" + cur + " W) is still the lowest step that makes the deadline." };
}

/** What the fallback policy holds when the normal plan cannot run. Never above the safe ceiling or the grid headroom cap; a limit that cannot be checked means no recommendation. */
function computeFallback(input: GentleInput, p: GentleParams, pol: GentlePolicy, why: string, cCeil: number | null, cMin: number, hh: HouseholdEval): FallbackInfo {
  const policy = pol.fallbackPolicy;
  const mk = (setpointW: number | null, reason: string): FallbackInfo => ({ applied: true, policy, setpointW, reason });
  if (policy === "NONE") return mk(null, why + " Fallback policy NONE: no recommendation.");
  if (cCeil === null) return mk(null, why + " The safe ceiling is unknown, so no setpoint can be checked against it: no recommendation.");
  if (hh.problem !== null) return mk(null, why + " The grid headroom cannot be checked (the household input is unusable): no recommendation.");
  let cap = cCeil;
  if (hh.capW !== null) cap = Math.min(cap, floorStep(hh.capW, p.stepW));
  if (cap < cMin) return mk(null, why + " No setpoint is safe: the highest safe limit (" + cap + " W) is below the minimum setpoint: no recommendation.");
  if (policy === "KEEP_CURRENT") {
    const cur = input.currentSetpointW;
    if (!isNum(cur) || cur <= 0) return mk(null, why + " Fallback KEEP_CURRENT: no setpoint is in force to keep: no recommendation.");
    if (cur > cap + 1e-9) return mk(null, why + " Fallback KEEP_CURRENT: the setpoint in force (" + cur + " W) is above the safe limit (" + cap + " W), so it is not kept: no recommendation.");
    return mk(cur, why + " Fallback KEEP_CURRENT: hold the setpoint in force (" + cur + " W), within the safe limit of " + cap + " W. A fallback, not a plan.");
  }
  const r = input.staticPlanRateW;
  if (!isNum(r) || r < cMin) return mk(null, why + " Fallback USE_STATIC_PLAN: no usable static plan rate was given: no recommendation.");
  const w = floorStep(Math.min(r, cap), p.stepW);
  if (w < cMin) return mk(null, why + " Fallback USE_STATIC_PLAN: the static rate cannot be brought within the safe limit: no recommendation.");
  return mk(w, why + " Fallback USE_STATIC_PLAN: use the static plan rate" + (w < r ? ", lowered from " + r + " W to the safe limit" : "") + " (" + w + " W). A fallback, not a plan.");
}

export function planGentle(input: GentleInput): GentleDecision {
  const target = (input && isNum(input.targetSocPct) ? input.targetSocPct : NaN) as number;
  const used = input && isNum(input.changesUsed) ? input.changesUsed : 0;
  const fail = (reason: string, p: GentleParams | null = null) => shell("INVALID", target, [reason + " Nothing is recommended."], ["INVALID_INPUT"], p, used);
  if (!input || typeof input !== "object") return fail("The input is missing.");
  const p = mergeParams(input.params);
  const pp = paramProblem(p);
  if (pp) return fail(pp);
  const pol = mergePolicy(input.policy);
  const polProblem = policyProblem(pol);
  if (polProblem) return fail(polProblem, p);
  const ip = inputProblem(input);
  if (ip) return fail(ip, p);

  const windowReal = windowRealMinutes(input.chargeWindow.startMin, input.chargeWindow.endMin, input.chargeWindow.clockDay) as number;
  const toDeadline = windowReal - input.bufferMin - input.elapsedMin;
  const toEnd = windowReal - input.elapsedMin;
  const cMin = ceilStep(p.minW, p.stepW);
  const known = smallestKnownCeiling(input.ceilings);
  const cCeil = known === null ? null : floorStep(Math.min(known.watts, p.hardMaxW), p.stepW);
  let hhMemo: HouseholdEval | null = null;
  const hhEval = (): HouseholdEval => (hhMemo ??= evalHousehold(input.household, p, pol, toEnd));
  const mk = (status: GentleStatus, reasons: string[], codes: GentleCode[]) => shell(status, target, reasons, codes, p, used, pol.fallbackPolicy);
  const withFallback = (d: GentleDecision, why: string, names: readonly string[]): GentleDecision => {
    d.fallback = computeFallback(input, p, pol, why, cCeil, cMin, hhEval());
    d.provisionalInUse = provisionalList([...names, "fallbackPolicy"], p, pol, input);
    return d;
  };

  // Unknown or stale SOC: no recommendation (never a guess); the fallback policy says what to hold.
  const noData = (reason: string, code: GentleCode) => withFallback(mk("NO_DATA", [reason], [code]), "The SOC is unknown, stale or implausible.", ["maxSocAgeMin"]);
  if (input.socPct === null || !isNum(input.socPct)) return noData("The SOC is unknown; nothing is recommended.", "NO_SOC");
  if (input.socPct < 0 || input.socPct > 100) return noData("The SOC reading is not plausible (" + input.socPct + " %); nothing is recommended.", "NO_SOC");
  if (input.socAgeMin === null || !isNum(input.socAgeMin) || input.socAgeMin < 0 || input.socAgeMin > p.maxSocAgeMin) {
    return noData("The SOC reading is stale or its age is unknown (limit " + p.maxSocAgeMin + " min); nothing is recommended.", "STALE_SOC");
  }
  const soc = input.socPct;
  if (soc >= target) {
    const d = mk("NOTHING_TO_CHARGE", ["The battery is at " + soc + " %, at or above the " + target + " % target."], ["AT_TARGET"]);
    d.provisionalInUse = provisionalList(["maxSocAgeMin"], p, pol, input);
    return d;
  }

  // The safe ceiling: the smallest KNOWN one, rounded down to a step, capped at the editor maximum. None known = no recommendation.
  if (known === null || cCeil === null) {
    return withFallback(mk("NO_SAFE_CEILING", ["No safe power ceiling is known (owner maximum, battery maximum charge power, grid-charge power); no default is guessed and nothing is recommended."], ["NO_CEILING"]), "No safe ceiling is known.", []);
  }
  const cMax0 = cCeil;
  if (cMax0 < cMin) {
    return withFallback(mk("NO_SAFE_CEILING", ["The smallest known ceiling (" + known.name + ", " + Math.round(known.watts) + " W) is below the minimum setpoint of " + cMin + " W; nothing is recommended."], ["CEILING_BELOW_MIN"]), "The ceiling is below the minimum setpoint.", []);
  }

  // The grid headroom (household inputs): a cap on the setpoint, never above the ceiling. An unusable household input with a known limit means no recommendation.
  const hh = hhEval();
  if (hh.problem !== null) {
    const bad = mk("NO_DATA", [hh.problem + " The safe grid headroom cannot be checked; nothing is recommended."], hh.codes.slice());
    return withFallback(bad, "The household input is unusable.", ["maxHouseholdAgeMin", "unknownDemandPolicy"]);
  }
  let cMax = cMax0;
  let headroomBinds = false;
  let capStep: number | null = null;
  if (hh.capW !== null) {
    capStep = floorStep(hh.capW, p.stepW);
    if (capStep < cMax0) {
      cMax = capStep;
      headroomBinds = true;
    }
  }
  const householdNames: string[] = hh.given && hh.limitW !== null ? ["demandMarginPct", "maxHouseholdAgeMin", ...(hh.basis === "ASSUMED" ? ["assumedDemandW", "unknownDemandPolicy"] : [])] : [];
  const hold = target >= 100 ? p.topHoldMin : 0;
  const slewNames = p.maxDecreaseStepW < p.hardMaxW ? ["maxDecreaseStepW"] : [];
  const provNames = [...CORE_NAMES, ...(hold > 0 ? ["topHoldMin"] : []), ...householdNames, ...slewNames];
  const summary = (): string => "Grid headroom: limit " + Math.round(hh.limitW as number) + " W, household demand peak " + Math.round(hh.peakW as number) + " W (with the " + p.demandMarginPct + " % margin), least solar counted " + Math.round(hh.solarMinW as number) + " W: the setpoint is capped at " + (capStep as number) + " W.";
  if (cMax < cMin) {
    const d = mk("NO_SAFE_CEILING", ["The grid headroom allows " + (capStep as number) + " W, below the minimum setpoint of " + cMin + " W. " + summary() + " Nothing is recommended."], ["HEADROOM_BELOW_MIN"]);
    d.ceilingW = cMax0;
    d.ceilingName = known.name;
    d.headroomCapW = capStep;
    d.household = householdReport(hh, null, p, "Grid headroom below the minimum setpoint.");
    return withFallback(d, "The grid headroom is below the minimum setpoint.", ["demandMarginPct", "maxHouseholdAgeMin"]);
  }

  // Time: real minutes, clock-change aware (the window length uses elapsedMinutes; elapsed is a monotonic count).
  const capPess = Math.max(input.capacityKwh, input.learnedCapacityKwh ?? 0) * (1 + input.capacityUpPct / 100);
  const model: ChargeModel = { capacityKwh: capPess, chargeEff: p.chargeEff, ceilingW: cMax0, taperStartSocPct: p.taperStartSocPct, taperEndFraction: p.taperEndFraction };
  if (hh.perMinW !== null) model.headroomW = hh.perMinW;
  const sinceChange = input.lastChangeElapsedMin === null ? Infinity : input.elapsedMin - input.lastChangeElapsedMin;
  const budgetLeft = p.maxChanges - used;
  const cur = input.currentSetpointW;

  const out = mk("OK", [], []);
  out.ceilingW = cMax0;
  out.ceilingName = known.name;
  out.deadlineInMin = toDeadline;
  out.windowEndInMin = toEnd;
  out.headroomCapW = capStep;
  out.limitedBy = headroomBinds ? "GRID_HEADROOM" : "CEILING";
  const limitWord = headroomBinds ? "safe grid headroom" : "safe ceiling";
  const limitName = headroomBinds ? "grid headroom" : known.name;
  // The recovery hold (a rising cap waits like a saving) applies only where the grid headroom is what limits the setpoint. A known limit that does
  // not bind leaves the ceiling as the target, and an increase toward it is a deadline need that is never held back by hysteresis or dwell.
  const ctx = (recovery: boolean, canWait?: (remMin: number) => boolean): ChooseCtx => ({ ceilW: cMax0, recovery: recovery && headroomBinds, headroomBinds, canWait });

  // Plan from the pessimistic end of the reading's rounding: a reading of 50 may be 49.5.
  const planSoc = Math.max(0, soc - p.socResolutionPct / 2);
  const finish = (w: number, maxMin: number, sample = 0) => projectCharge(planSoc, w, target, model, maxMin, sample);
  const done = (): GentleDecision => {
    out.provisionalInUse = provisionalList(provNames, p, pol, input);
    if (hh.given) {
      out.codes.push(...hh.codes);
      out.reasons.push(...hh.reasons);
      if (hh.limitW !== null) {
        if (headroomBinds) {
          out.codes.push("HEADROOM_LIMITED");
          out.reasons.push(summary());
        }
        const imp = out.setpointW === null ? null : gridImportW(out.setpointW * p.chargeEff, p.chargeEff, hh.peakW as number, hh.solarMinW as number);
        out.household = householdReport(hh, imp, p, headroomBinds ? "The grid headroom limits the setpoint." : "The grid headroom does not bind.");
      } else out.household = householdReport(hh, null, p, "No grid limit is known: no headroom constraint.");
      if (out.status === "TARGET_AT_RISK" || out.status === "TARGET_UNREACHABLE") out.reasons.push("The target is NOT guaranteed.");
    }
    return out;
  };
  const finalise = (c: Choice) => {
    out.setpointW = c.w;
    out.change = c.change;
    out.changeRecommended = c.change !== "NONE";
    out.codes.push(c.code);
    if (c.extra) out.codes.push(...c.extra);
    out.jumpForDeadline = c.extra !== undefined && c.extra.includes("JUMP_FOR_DEADLINE");
    out.reasons.push(c.reason);
    // The START and a safety decrease do not draw on the budget; an ordinary increase or decrease does.
    out.changesUsed = used + (c.change === "INCREASE" || c.code === "DECREASE_SAVING" ? 1 : 0);
    out.changesLeft = Math.max(0, p.maxChanges - out.changesUsed);
    const pr = c.lead
      ? projectCharge(planSoc, cMax, target, { ...model, leadW: c.lead.w, leadMin: c.lead.min }, Math.max(toEnd - hold, 0), 5)
      : finish(c.w, Math.max(toEnd - hold, 0), 5);
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
      const c = choose(cMax, cMax, cMax, cur, sinceChange, budgetLeft, p, ctx(true));
      finalise(c);
      out.reasons.push("Time is left before the window ends: the " + (headroomBinds ? "safe grid headroom" : "ceiling") + " is the best effort.");
    }
    return done();
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
    // Even the highest safe setpoint is late against the deadline: clipped there, never a lower target.
    const atCeiling = finish(cMax, Math.max(toEnd - hold, 0)).finishMin;
    const c = choose(cMax, cMax, cMax, cur, sinceChange, budgetLeft, p, ctx(true));
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
      out.reasons.push("Buffer too small: the target needs more than the " + limitWord + " of " + cMax + " W (" + limitName + ") to finish by the deadline; " + (headroomBinds ? "at that limit" : "at the ceiling") + " it finishes about " + Math.ceil(lateBy as number) + " min late, inside the buffer. The target is not lowered.");
    } else {
      out.status = "TARGET_UNREACHABLE";
      out.codes.push("TARGET_UNREACHABLE");
      out.reasons.push("Buffer too small, or the target is out of reach: even at the " + limitWord + " of " + cMax + " W (" + limitName + ") the target is not reached before the window ends. The target is not lowered.");
    }
    return done();
  }

  const downW = p.decreaseSlackMin > 0 ? lowestStep(avail - p.decreaseSlackMin) ?? cMax : neededW;
  const canWait = hh.capW !== null && cur !== null && cur > 0
    ? (remMin: number): boolean => projectCharge(planSoc, cMax, target, { ...model, leadW: cur, leadMin: Math.ceil(remMin) }, avail - p.decreaseSlackMin).finishMin !== null
    : undefined;
  const c = choose(neededW, downW, cMax, cur, sinceChange, budgetLeft, p, ctx(false, canWait));
  const pr = finalise(c);
  if (c.code === "START" || c.code === "INCREASE_FOR_DEADLINE" || c.code === "DECREASE_SAVING" || c.code === "ABOVE_CEILING" || c.code === "ABOVE_HEADROOM") {
    out.codes.push(neededW === cMax ? "AT_CEILING" : "LOWEST_STEP");
    out.reasons.push(neededW === cMax ? "The lowest step that makes the deadline is the " + limitWord + " itself." : "Lowest step whose forward simulation (pessimistic capacity, assumed taper) reaches the target by the deadline.");
  }
  if (pr.finishMin === null || pr.finishMin > avail + 1e-9) {
    // The setpoint in force (kept by dwell, hysteresis or an exhausted budget) would finish late although the ceiling could make it.
    out.status = "TARGET_AT_RISK";
    out.codes.push("TARGET_AT_RISK");
    out.reasons.push("The setpoint that stays in force would finish after the deadline; a higher setpoint is held back by the changes budget. The target is not lowered.");
  }
  return done();
}

function householdReport(hh: HouseholdEval, importW: number | null, p: GentleParams, note: string): HouseholdReport {
  return {
    gridLimitW: hh.limitW,
    demandBasis: hh.basis,
    demandPeakW: hh.peakW === null ? null : round1(hh.peakW),
    solarCountedMinW: hh.solarMinW === null ? null : round1(hh.solarMinW),
    projectedImportW: importW === null ? null : round1(importW),
    note: note + (hh.basis === "ASSUMED" ? " Demand is the provisional assumption of " + p.assumedDemandW + " W at least." : ""),
  };
}
