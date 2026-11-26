// Gentle charge RATE ADVICE: a stateless, READ-ONLY recommendation of the gentlest charge rate that still reaches the chosen target SOC by the
// finish-early deadline. Pure data in, data out: no I/O, no clock, no class, no state between calls.
//
// This is a thin layer over `planGentle` (gentleController.ts), not a second controller. It asks the model the stateless question "with nothing in
// force yet, what is the lowest rate that makes the deadline from here?" (no current setpoint, so no hysteresis, dwell, slew or changes budget) and
// returns the answer with ONE primary reason code, an outcome (on time, late, missed, at target, unknown), the practical minimum, the safe maximum,
// the margins the rate already carries and, when a pack voltage is given, the same rate as a current. Calling it at every re-plan tick with the
// latest reading is the adaptive part; the anti-flapping rules of the full model stay in `planGentle`.
//
// NOTHING HERE ACTUATES. No service call, no helper, no schedule, no mode, no published value is touched, and the advice says it is "model, not a
// command". Missing, stale or implausible data gives NO advice and says why (never a guess). The target is never lowered and never guaranteed.
import { ampsFromPower, planGentle, CONTROLLER_LABEL, NO_GUARANTEE_NOTE, ACTUATION_REASON, DEFAULT_GENTLE_PARAMS } from "./gentleController.ts";
import type { GentleCode, GentleDecision, GentleInput, GentleParams, GentlePolicy, GentleStatus } from "./gentleController.ts";

/** What the advice is: a rate that makes the deadline, a best effort that does not, nothing to charge, or no advice. */
export type AdviceKind = "RATE" | "BEST_EFFORT" | "NOTHING_TO_CHARGE" | "NO_ADVICE";

/** Whether the target is reached by the deadline at the advised rate (projected, assumed battery behaviour): never a promise. */
export type AdviceOutcome = "ON_TIME" | "LATE" | "MISSED" | "AT_TARGET" | "UNKNOWN";

/** The ONE primary reason of a piece of advice. Secondary codes of the underlying decision are in `codes`. */
export type AdviceReason =
  | "RATE_GENTLEST"
  | "RATE_AT_PRACTICAL_MINIMUM"
  | "RATE_AT_SAFE_MAXIMUM"
  | "BEST_EFFORT_AT_RISK"
  | "BEST_EFFORT_UNREACHABLE"
  | "BEST_EFFORT_DEADLINE_PASSED"
  | "AT_TARGET"
  | "NO_SOC"
  | "STALE_SOC"
  | "SOC_IMPLAUSIBLE"
  | "NO_SAFE_CEILING"
  | "CEILING_BELOW_MIN"
  | "HEADROOM_BELOW_MIN"
  | "HOUSEHOLD_UNUSABLE"
  | "HOUSEHOLD_INVALID"
  | "GRID_LIMIT_STALE"
  | "WINDOW_ENDED"
  | "INVALID_INPUT"
  | "NO_SETPOINT";

/** A caution that rides along with the advice and never changes it (the rate, the outcome and the reason are the same with or without it). */
export type AdviceWarningCode = "CEILING_AGE_UNKNOWN" | "TOP_OF_CHARGE_TAIL";

export interface AdviceWarning {
  code: AdviceWarningCode;
  text: string;
}

/** Every reason the advice can carry (a closed list; the tests pin that nothing else is ever returned). */
export const ADVICE_REASONS: readonly AdviceReason[] = [
  "RATE_GENTLEST", "RATE_AT_PRACTICAL_MINIMUM", "RATE_AT_SAFE_MAXIMUM", "BEST_EFFORT_AT_RISK", "BEST_EFFORT_UNREACHABLE", "BEST_EFFORT_DEADLINE_PASSED",
  "AT_TARGET", "NO_SOC", "STALE_SOC", "SOC_IMPLAUSIBLE", "NO_SAFE_CEILING", "CEILING_BELOW_MIN", "HEADROOM_BELOW_MIN", "HOUSEHOLD_UNUSABLE",
  "HOUSEHOLD_INVALID", "GRID_LIMIT_STALE", "WINDOW_ENDED", "INVALID_INPUT", "NO_SETPOINT",
];

/** Optional pack data, only to express the advised power as a current. The firmware turns watts into amps at the pack voltage when a rate is applied. */
export interface BatteryElectrics {
  /** Pack voltage now in V, or null when unknown (then no current is given). */
  volts: number | null;
  /** The lowest voltage the pack can show while the rate is in force; the lower of the two is used, because a lower voltage means more amps for the same watts. */
  minVolts?: number | null;
  /** The pack's charge current limit in A, when known: the current is never above it. */
  maxChargeAmps?: number | null;
}

/**
 * The inputs of the model WITHOUT its state (no setpoint in force, no last change, no changes budget, no static plan rate): the advice has no memory.
 * The policy keeps only the two choices that change what a rate means (`unknownDemandPolicy`, `setpointBasis`); there is no fallback to hold.
 */
export type GentleAdviceInput = Omit<GentleInput, "currentSetpointW" | "lastChangeElapsedMin" | "changesUsed" | "totalChangesUsed" | "staticPlanRateW" | "policy"> & {
  policy?: Partial<Pick<GentlePolicy, "unknownDemandPolicy" | "setpointBasis">>;
  battery?: BatteryElectrics | null;
};

/** The margins a rate already carries (all are inputs or stated assumptions, none is added on top of the lowest step). */
export interface AdviceMargins {
  /** The finish-early buffer (the owner's setting): the deadline is the window end minus this. */
  bufferMin: number;
  /** The capacity band: the plan assumes the capacity may be this much higher than nominal, which needs more energy. */
  capacityBandPct: number;
  /** The plan starts from the reading minus this many percentage points (half the SOC resolution). */
  socOffsetPct: number;
  /** Extra minutes reserved after a 100 % target (the top-of-charge hold); 0 for a lower target. */
  topHoldMin: number;
  /** The BMS taper the projection assumes (assumed, not measured). */
  taperStartSocPct: number;
  taperEndFraction: number;
  /** Minutes from the projected finish to the deadline, or null when no finish is projected. */
  marginMin: number | null;
}

export interface GentleAdvice {
  label: typeof CONTROLLER_LABEL;
  advice: AdviceKind;
  /** The one primary reason code. */
  reason: AdviceReason;
  outcome: AdviceOutcome;
  /** True when the target is projected to miss the deadline (LATE or MISSED). It is never a promise either way. */
  targetWillBeMissed: boolean;
  /** The model's own status for the decision this advice was made from. */
  status: GentleStatus;
  /** True when the plan rests on an explicitly requested assumed demand (status DEGRADED): usable, never a normal OK. */
  degraded: boolean;
  /** The advised rate in W (setpoint units), or null when there is no advice or nothing to charge. A multiple of the step within [practical minimum, safe maximum]. */
  rateW: number | null;
  /** The same rate as a current in A at the lowest given pack voltage (never above the current limit), or null when no voltage was given. */
  rateAmps: number | null;
  /** The lowest step that reaches the target by the deadline, or null when none up to the safe maximum does. For a RATE it equals `rateW`. */
  neededW: number | null;
  /** The lowest rate this advice ever offers (the practical minimum, rounded up to a step); it is never advised below. */
  minRateW: number;
  /** The highest safe rate: the smaller of the ceiling and the grid headroom cap. Null when no safe ceiling is known. */
  safeMaxW: number | null;
  limitedBy: GentleDecision["limitedBy"];
  deadlineInMin: number | null;
  finishInMin: number | null;
  /** Minutes the projection leaves before the deadline (negative: late). Null when no finish is projected. */
  marginMin: number | null;
  margins: AdviceMargins;
  /** A short sentence for a person. */
  summary: string;
  /** The model's own reasons, in order. */
  explanation: string[];
  /** Every code of the underlying decision, the primary one included. */
  codes: GentleCode[];
  /** Cautions about a labelled limitation that applies to this input (none changes the advice): a ceiling taken as current without an age, a 100 % target's tail. */
  warnings: AdviceWarning[];
  /** The underlying decision, for audit. */
  decision: GentleDecision;
  actuationSupported: false;
  actuationReason: string;
  guarantee: "NONE";
  guaranteeNote: string;
}

const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const round1 = (x: number): number => Math.round(x * 10) / 10;
const ceilStep = (x: number, step: number): number => Math.ceil(x / step - 1e-9) * step;

/** The value of one numeric parameter in force: the caller's when it is a finite number, else the default (the model validates the rest). */
function paramValue(params: Partial<GentleParams> | undefined, name: keyof GentleParams): number {
  const v = params === undefined || params === null ? undefined : params[name];
  return isNum(v) ? v : (DEFAULT_GENTLE_PARAMS[name] as number);
}

function firstCode(codes: readonly GentleCode[], wanted: readonly GentleCode[]): GentleCode | null {
  for (const w of wanted) if (codes.includes(w)) return w;
  return null;
}

function currentFrom(rateW: number | null, b: BatteryElectrics | null | undefined): number | null {
  if (rateW === null || b === undefined || b === null || typeof b !== "object") return null;
  const lowest = isNum(b.minVolts) && b.minVolts > 0 && isNum(b.volts) ? Math.min(b.volts, b.minVolts) : b.volts;
  const limit = isNum(b.maxChargeAmps) && b.maxChargeAmps >= 0 ? b.maxChargeAmps : Number.MAX_VALUE;
  const amps = ampsFromPower(rateW, lowest, limit);
  return amps === null ? null : round1(amps);
}

/**
 * The labelled limitations that apply to this input, said where the reader sees the advice. Nothing here changes a rate: a safe ceiling given with no age is
 * trusted as current (a limit that changed or went quiet is not noticed), and at a 100 % target the battery may go on charging after the reading reaches 100.
 */
function warningsOf(input: GentleAdviceInput): AdviceWarning[] {
  const out: AdviceWarning[] = [];
  if (input === null || typeof input !== "object") return out;
  const ceilings: unknown[] = Array.isArray(input.ceilings) ? input.ceilings : [];
  const undated: string[] = [];
  for (const c of ceilings as Array<{ name?: unknown; watts?: unknown; ageMin?: unknown } | null>) {
    if (c !== null && typeof c === "object" && isNum(c.watts) && c.watts >= 0 && (c.ageMin === undefined || c.ageMin === null)) undated.push(typeof c.name === "string" ? c.name : "unnamed");
  }
  if (undated.length > 0) {
    out.push({ code: "CEILING_AGE_UNKNOWN", text: "These safe ceilings came with no age and are taken as current: " + undated.join(", ") + ". A limit that changed, or a reading that went quiet, would not be noticed." });
  }
  if (isNum(input.targetSocPct) && input.targetSocPct >= 100) {
    out.push({ code: "TOP_OF_CHARGE_TAIL", text: "At a 100 % target the battery may keep charging for a while after the reading reaches 100 (the top of charge is the BMS's own business). The plan only reserves that time before the deadline; stopping at the first reading of 100 would cut it off." });
  }
  return out;
}

function marginsOf(input: GentleAdviceInput, d: GentleDecision): AdviceMargins {
  const p = input !== null && typeof input === "object" ? input.params : undefined;
  return {
    bufferMin: isNum(input?.bufferMin) ? input.bufferMin : NaN,
    capacityBandPct: isNum(input?.capacityUpPct) ? input.capacityUpPct : NaN,
    socOffsetPct: paramValue(p, "socResolutionPct") / 2,
    topHoldMin: isNum(input?.targetSocPct) && input.targetSocPct >= 100 ? paramValue(p, "topHoldMin") : 0,
    taperStartSocPct: paramValue(p, "taperStartSocPct"),
    taperEndFraction: paramValue(p, "taperEndFraction"),
    marginMin: d.marginMin,
  };
}

/**
 * Turns a model decision (made with nothing in force) into advice. Exported so that the fail-closed default can be tested: a decision that does not
 * fit any rule here is NO_ADVICE with the reason NO_SETPOINT, never a rate.
 */
export function adviceFromDecision(d: GentleDecision, input: GentleAdviceInput): GentleAdvice {
  const step = paramValue(input?.params, "stepW");
  const minRateW = ceilStep(paramValue(input?.params, "minW"), step >= 1 ? step : (DEFAULT_GENTLE_PARAMS.stepW as number));
  const safeMaxW = d.ceilingW === null ? null : d.headroomCapW === null ? d.ceilingW : Math.min(d.ceilingW, d.headroomCapW);
  let advice: AdviceKind = "NO_ADVICE";
  let reason: AdviceReason = "NO_SETPOINT";
  let outcome: AdviceOutcome = "UNKNOWN";
  const rate = d.setpointW;

  if ((d.status === "OK" || d.status === "DEGRADED") && rate !== null && d.marginMin !== null && d.marginMin >= 0) {
    advice = "RATE";
    outcome = "ON_TIME";
    reason = safeMaxW !== null && rate >= safeMaxW ? "RATE_AT_SAFE_MAXIMUM" : rate <= minRateW ? "RATE_AT_PRACTICAL_MINIMUM" : "RATE_GENTLEST";
  } else if (d.status === "TARGET_AT_RISK" && rate !== null) {
    advice = "BEST_EFFORT";
    reason = "BEST_EFFORT_AT_RISK";
    outcome = "LATE";
  } else if (d.status === "TARGET_UNREACHABLE" && rate !== null) {
    advice = "BEST_EFFORT";
    reason = "BEST_EFFORT_UNREACHABLE";
    outcome = "MISSED";
  } else if (d.status === "DEADLINE_PASSED") {
    if (rate !== null) {
      advice = "BEST_EFFORT";
      reason = "BEST_EFFORT_DEADLINE_PASSED";
      outcome = d.finishInMin !== null ? "LATE" : "MISSED";
    } else {
      reason = "WINDOW_ENDED";
      outcome = "MISSED";
    }
  } else if (d.status === "NOTHING_TO_CHARGE") {
    advice = "NOTHING_TO_CHARGE";
    reason = "AT_TARGET";
    outcome = "AT_TARGET";
  } else if (d.status === "NO_SAFE_CEILING") {
    const c = firstCode(d.codes, ["CEILING_BELOW_MIN", "HEADROOM_BELOW_MIN", "NO_CEILING"]);
    reason = c === "CEILING_BELOW_MIN" ? "CEILING_BELOW_MIN" : c === "HEADROOM_BELOW_MIN" ? "HEADROOM_BELOW_MIN" : "NO_SAFE_CEILING";
    // No safe rate reaches even the practical minimum: the model will not charge, so the target is missed; an unknown ceiling is only unknown.
    outcome = c === "CEILING_BELOW_MIN" || c === "HEADROOM_BELOW_MIN" ? "MISSED" : "UNKNOWN";
  } else if (d.status === "NO_DATA") {
    const c = firstCode(d.codes, ["NO_SOC", "STALE_SOC", "SOC_IMPLAUSIBLE", "GRID_LIMIT_STALE", "HOUSEHOLD_INVALID", "HOUSEHOLD_UNUSABLE"]);
    reason = c === null ? "NO_SETPOINT" : (c as AdviceReason);
  } else if (d.status === "INVALID") {
    reason = "INVALID_INPUT";
  }

  const rateW = advice === "RATE" || advice === "BEST_EFFORT" ? rate : null;
  const out: GentleAdvice = {
    label: CONTROLLER_LABEL,
    advice,
    reason,
    outcome,
    targetWillBeMissed: outcome === "LATE" || outcome === "MISSED",
    status: d.status,
    degraded: d.status === "DEGRADED",
    rateW,
    rateAmps: currentFrom(rateW, input?.battery),
    neededW: d.neededW,
    minRateW,
    safeMaxW,
    limitedBy: d.limitedBy,
    deadlineInMin: d.deadlineInMin,
    finishInMin: d.finishInMin,
    marginMin: d.marginMin,
    margins: marginsOf(input, d),
    summary: "",
    explanation: d.reasons.slice(),
    codes: d.codes.slice(),
    warnings: warningsOf(input),
    decision: d,
    actuationSupported: false,
    actuationReason: ACTUATION_REASON,
    guarantee: "NONE",
    guaranteeNote: NO_GUARANTEE_NOTE,
  };
  out.summary = summaryOf(out, input);
  return out;
}

function summaryOf(a: GentleAdvice, input: GentleAdviceInput): string {
  const target = isNum(input?.targetSocPct) ? input.targetSocPct + " %" : "the target";
  const w = a.rateW === null ? "" : a.rateW + " W";
  switch (a.reason) {
    case "RATE_GENTLEST":
      return "Charge at " + w + ": the lowest rate that reaches " + target + " by the deadline (" + Math.floor(a.marginMin as number) + " min to spare in the projection).";
    case "RATE_AT_PRACTICAL_MINIMUM":
      return "Charge at " + w + ", the practical minimum: it reaches " + target + " by the deadline and nothing gentler is offered.";
    case "RATE_AT_SAFE_MAXIMUM":
      return "Charge at " + w + ", the highest safe rate: nothing gentler reaches " + target + " by the deadline.";
    case "BEST_EFFORT_AT_RISK":
      return "The target will be missed: even the highest safe rate (" + w + ") finishes about " + Math.ceil(-(a.marginMin as number)) + " min after the deadline, inside the buffer. Best effort only.";
    case "BEST_EFFORT_UNREACHABLE":
      return "The target will be missed: " + target + " is not reached before the window ends even at the highest safe rate (" + w + "). Best effort only.";
    case "BEST_EFFORT_DEADLINE_PASSED":
      return "The deadline has passed with the battery below the target, so the target will be missed; " + w + " is the best effort while the window lasts.";
    case "AT_TARGET":
      return "The battery is at or above the target: nothing to charge.";
    default:
      return "No advice: " + (a.explanation[0] ?? "the inputs do not allow a recommendation") + (a.targetWillBeMissed ? " The target will be missed." : "");
  }
}

/**
 * The gentlest charge rate that still reaches the target by the deadline, from the state given. Pure and deterministic: the same input always gives the
 * same advice, and the input is never changed. With unknown, stale or implausible data (SOC, a safe ceiling, a known grid limit and its demand) there is
 * NO advice and the reason says why. The rate is never above the smallest known safe ceiling or the grid headroom cap, never above the lowest 100 W step
 * that makes the deadline, and never below the practical minimum (when no safe rate reaches the minimum there is no advice and the target is missed).
 */
export function adviseGentleRate(input: GentleAdviceInput): GentleAdvice {
  if (input === null || typeof input !== "object") {
    const d = planGentle(input as unknown as GentleInput);
    return adviceFromDecision(d, { ...(input as object) } as GentleAdviceInput);
  }
  const pol = input.policy !== null && typeof input.policy === "object" ? input.policy : {};
  const stateless: GentleInput = {
    targetSocPct: input.targetSocPct,
    bufferMin: input.bufferMin,
    chargeWindow: input.chargeWindow,
    elapsedMin: input.elapsedMin,
    socPct: input.socPct,
    socAgeMin: input.socAgeMin,
    capacityKwh: input.capacityKwh,
    capacityUpPct: input.capacityUpPct,
    learnedCapacityKwh: input.learnedCapacityKwh,
    ceilings: input.ceilings,
    currentSetpointW: null,
    lastChangeElapsedMin: null,
    changesUsed: 0,
    previousSoc: input.previousSoc,
    params: input.params,
    household: input.household,
    policy: { fallbackPolicy: "NONE", unknownDemandPolicy: pol.unknownDemandPolicy, setpointBasis: pol.setpointBasis },
    staticPlanRateW: null,
  };
  return adviceFromDecision(planGentle(stateless), input);
}
