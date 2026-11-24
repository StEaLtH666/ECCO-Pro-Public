// Gentle Smart Charging: READ-ONLY controller MODEL (owner directive 17 and 18 Nov 2026). Pure data in, data out: no I/O, no clock, no class.
//
// At each tick it turns the state into a RECOMMENDED charge-power setpoint: the lowest 100 W step whose forward simulation (pessimistic
// capacity, assumed BMS taper) reaches the target by the deadline (window end minus the finish-early buffer), then hysteresis, dwell, a
// slew limit and a changes budget. It never lowers the target, never recommends a setpoint above a safe limit as its inputs and assumptions state it
// (a model estimate: the real limits may be lower) and never recommends from unknown or stale SOC.
// Optional household inputs (demand, solar, a KNOWN safe grid import limit) cap the setpoint by the grid headroom, pessimistically.
//
// NOTHING HERE ACTUATES. Today's firmware fixes the Free Power rate at START, so a recommended CHANGE cannot be applied: an actuator
// (a Free Power rate controller on the Dump V1.1 pattern, with a write budget and live proof) does not exist. The module only says what
// such a controller would do, and labels it "model, not a command". It NEVER guarantees the target (guarantee is always NONE).
import { ambiguousClockStart, elapsedMinutes, span } from "./time.ts";
import type { ClockDay } from "./time.ts";
import { LIMITS } from "./settings.ts";

export const CONTROLLER_LABEL = "model, not a command";
export const ASSUMED_LABEL = "assumed, not measured";
export const ACTUATION_REASON =
  "Today's firmware fixes the Free Power rate at START and verifies against it; applying a change needs a rate controller that does not exist (it would need a write budget and live proof).";
export const NO_GUARANTEE_NOTE =
  "The target is NOT guaranteed. This is a plan from assumed battery behaviour, forecasts and the latest readings, not a promise: a 100 percent target is the most at risk, because the BMS is expected to taper the charge near full and to handle the top of charge itself (assumed here, not measured), so a fixed rate is unlikely to finish a full charge on time, and a lost reading, a demand spike or a lower real limit can make any target miss. The model is read-only: it recommends and applies nothing.";
/** The default finish-early buffer in minutes (the owner's setting; the 0-120 grid in 5-minute steps is unchanged). Used by helpers and tests. */
export const GENTLE_DEFAULT_BUFFER_MIN = 60;

/** Hard bounds of the numbers the model accepts (the buffer step is the owner's 5-minute grid). */
export const GENTLE_BOUNDS = Object.freeze({ targetMin: 10, targetMax: 100, bufferMin: LIMITS.bufferMin, bufferMax: LIMITS.bufferMax, bufferStep: 5, replanMin: 5, replanMax: 15 });

export type GentleStatus = "OK" | "DEGRADED" | "NOTHING_TO_CHARGE" | "TARGET_AT_RISK" | "TARGET_UNREACHABLE" | "NO_DATA" | "NO_SAFE_CEILING" | "DEADLINE_PASSED" | "INVALID";
export type GentleChange = "NONE" | "START" | "INCREASE" | "DECREASE";
export type FallbackPolicy = "KEEP_CURRENT" | "USE_STATIC_PLAN" | "NONE";
export type UnknownDemandPolicy = "ASSUME_PROVISIONAL" | "FALLBACK";
/** Which side of the charger a power figure is measured on: GRID_AC (drawn from the grid) or BATTERY_DC (delivered to the battery). */
export type PowerBasis = "GRID_AC" | "BATTERY_DC";
/**
 * What the recommended setpoint S means to the actuator. GRID_AC: S is grid-side watts. BATTERY_DC: S is battery-side watts (grid draw = S / efficiency).
 * UNSETTLED (the default): not proven, so every cap is the lower of the two readings and holds under either convention.
 */
export type SetpointBasis = PowerBasis | "UNSETTLED";
export type ParamKind = "PROVISIONAL" | "OWNER_SET" | "MEASURED_REQUIRED";

/** The name of the single authoritative maximum-charge-power ceiling (see MAX_CHARGE_POWER_BASIS). */
export const MAX_CHARGE_POWER_NAME = "max_charge_power_effective";

/**
 * THE one authoritative maximum-charge-power basis of this model (offline resolution, 24 Nov 2026). It is a SETPOINT bound: the largest value the slot
 * power and the Free Power setpoints accept (a compile-time firmware bound, 8000 W today), lowered by the owner's operating limit; the effective figure
 * is the smaller of the two (the same rule as the effective maximum grid charge power figure of the site). It is NOT a measured battery-side power, NOT
 * the grid import limit, NOT the inverter's rated power and NOT a BMS limit: on four recorded nights the battery-side charge power was above it and the
 * grid import was well above it, so each of those stays a separate NAMED ceiling with its own basis, and this figure is never raised by them.
 */
export const MAX_CHARGE_POWER_BASIS = Object.freeze({
  name: MAX_CHARGE_POWER_NAME,
  kind: "SETPOINT_BOUND" as const,
  authoritativeW: LIMITS.chargePowerMax,
  effectiveRule: "min(firmware setpoint bound, owner operating limit); unknown when either is unknown",
  source: "the firmware slot-power bound (compile time) and the owner's grid charge operating limit helper; the planner's effective maximum grid charge power figure",
  isNot: Object.freeze([
    "a measured battery-side charge power (the realised power was above it on the nights checked)",
    "the grid import limit (the import was above it, and it is separate and unknown)",
    "the inverter's rated power or the battery's own current limit",
    "a BMS limit or a derating",
  ]),
  confidence: "Established by code for what it is; the realised power against it is established by saved data for one setpoint only; the setpoint unit stays UNSETTLED",
});

/** The effective maximum charge power as ONE named ceiling: the smaller of the firmware setpoint bound and the owner's operating limit; unknown (never guessed) when either is unknown. */
export function maxChargePowerCeiling(firmwareBoundW: number | null | undefined, operatingLimitW: number | null | undefined, ageMin?: number | null): NamedCeiling {
  const known = isNum(firmwareBoundW) && firmwareBoundW >= 0 && isNum(operatingLimitW) && operatingLimitW >= 0;
  const c: NamedCeiling = { name: MAX_CHARGE_POWER_NAME, watts: known ? Math.min(firmwareBoundW as number, operatingLimitW as number) : null };
  if (ageMin !== undefined) c.ageMin = ageMin;
  return c;
}

export type ActuatorProfileId = "UNCONSTRAINED" | "FREE_POWER_LEASE" | "TOU_SLOT_EDITOR" | "RATE_CONTROLLER_PROPOSED";

/** What a path that could apply a recommended rate allows. Every number is a CONSTRAINT on the model, never an authorisation: none is authorised to apply a recommendation. */
export interface ActuatorProfile {
  id: ActuatorProfileId;
  label: string;
  /** What the setpoint is on this path and in which unit. */
  setpointUnit: string;
  /** Granularity and range of the setpoint on this path. */
  stepW: number;
  minW: number;
  maxW: number;
  /** Least minutes between two changes. */
  minDwellMin: number;
  /** Ordinary changes after the START that the path allows per window (0 = the rate is fixed at the START). */
  maxAdjustmentsPerWindow: number;
  /** False when a rate can be set at the START only. */
  midWindowAdjustment: boolean;
  /** True when every change needs the owner's own typed confirmation (not automatic). */
  ownerConfirmationPerChange: boolean;
  existsToday: boolean;
  /** Always false: no path is authorised to apply a model recommendation. */
  automaticApplyAuthorised: false;
  limitation: string;
  source: string;
  /** Where each number comes from: CODE, DOCS, PROPOSED_POLICY (a design choice, not a device limit) or NOT_BUILT. */
  confidence: string;
}

export const GENTLE_ACTUATOR_PROFILES: Readonly<Record<ActuatorProfileId, Readonly<ActuatorProfile>>> = Object.freeze({
  UNCONSTRAINED: Object.freeze({
    id: "UNCONSTRAINED", label: "No path assumed (the generic model)", setpointUnit: "W (generic)", stepW: 100, minW: LIMITS.chargePowerMin, maxW: LIMITS.chargePowerMax,
    minDwellMin: 0, maxAdjustmentsPerWindow: 100, midWindowAdjustment: true, ownerConfirmationPerChange: false, existsToday: false, automaticApplyAuthorised: false as const,
    limitation: "No path is assumed: the generic model's own parameters apply unchanged.", source: "the model's defaults", confidence: "NOT_BUILT",
  }),
  FREE_POWER_LEASE: Object.freeze({
    id: "FREE_POWER_LEASE", label: "Free Power start (a fixed rate for a duration)", setpointUnit: "W, staged once; the firmware turns it into a grid-charge current at the battery voltage of that moment and sets the slot powers to it",
    stepW: 100, minW: LIMITS.chargePowerMin, maxW: LIMITS.chargePowerMax, minDwellMin: 0, maxAdjustmentsPerWindow: 0, midWindowAdjustment: false, ownerConfirmationPerChange: false,
    existsToday: true, automaticApplyAuthorised: false as const,
    limitation: "The rate is fixed at the START and verified against; a change from outside during a lease blocks the automatic restore; there is no stop at a target SOC.",
    source: "firmware Free Power START and restore classifier; docs/product-ui/FEASIBILITY_MATRIX.md 2.2", confidence: "CODE",
  }),
  TOU_SLOT_EDITOR: Object.freeze({
    id: "TOU_SLOT_EDITOR", label: "Guarded TOU slot editor (slot power), owner confirms each write", setpointUnit: "W, the slot power setting (a multiple of 100, 500 to the firmware bound)",
    stepW: 100, minW: LIMITS.chargePowerMin, maxW: LIMITS.chargePowerMax, minDwellMin: 60, maxAdjustmentsPerWindow: 1, midWindowAdjustment: true, ownerConfirmationPerChange: true,
    existsToday: true, automaticApplyAuthorised: false as const,
    limitation: "One field of one slot per request through Review, a typed confirmation and Apply; no durable snapshot and no rollback; refused near slot boundaries, in a lease and on clock-change nights; no live proof of a charge-rate response below the top rate.",
    source: "the TOU editor package and docs (one field per request, 500 to 8000 W in steps of 100); dwell and adjustment count are PROPOSED policy, not device limits", confidence: "CODE for the range and step; PROPOSED_POLICY for dwell and count",
  }),
  RATE_CONTROLLER_PROPOSED: Object.freeze({
    id: "RATE_CONTROLLER_PROPOSED", label: "A guarded rate controller (does not exist)", setpointUnit: "W, the slot power setting, changed by a firmware controller on the Dump to Grid V1.1 pattern",
    stepW: 100, minW: LIMITS.chargePowerMin, maxW: LIMITS.chargePowerMax, minDwellMin: 30, maxAdjustmentsPerWindow: 6, midWindowAdjustment: true, ownerConfirmationPerChange: false,
    existsToday: false, automaticApplyAuthorised: false as const,
    limitation: "Not built, not reviewed, not proven: the proof list in GENTLE_LIVE_ACTUATION_PROOF.md must exist first.",
    source: "docs/product-ui/FEASIBILITY_MATRIX.md 2.2 (the Dump V1.1 limits are the template); the numbers are the model's own proposals", confidence: "NOT_BUILT",
  }),
});

/** What a decision says about the path it assumed. */
export interface ActuatorReport {
  profile: ActuatorProfileId;
  label: string;
  existsToday: boolean;
  midWindowAdjustment: boolean;
  maxAdjustmentsPerWindow: number;
  minDwellMin: number;
  stepW: number;
  rangeW: [number, number];
  setpointUnit: string;
  ownerConfirmationPerChange: boolean;
  automaticApplyAuthorised: false;
  /** The parameters this profile tightened (a profile never loosens a parameter). */
  tightened: string[];
  /** Whether the recommended change could be applied on this path: null when no change is recommended. */
  applicableNow: boolean | null;
  limitation: string;
}

/** The profile's constraints over the parameters: the stricter value always wins, a profile never loosens a parameter. */
export function applyActuatorProfile(p: GentleParams, id: ActuatorProfileId): { params: GentleParams; tightened: string[] } {
  const a = GENTLE_ACTUATOR_PROFILES[id];
  const out: GentleParams = { ...p };
  const tightened: string[] = [];
  const set = (k: "stepW" | "minW" | "hardMaxW" | "dwellMin" | "maxChanges", v: number) => {
    if (out[k] !== v) {
      out[k] = v;
      tightened.push(k);
    }
  };
  if (p.stepW % a.stepW !== 0) set("stepW", ceilStep(p.stepW, a.stepW));
  set("minW", Math.max(p.minW, a.minW));
  set("hardMaxW", Math.min(p.hardMaxW, a.maxW));
  set("dwellMin", Math.max(p.dwellMin, a.minDwellMin));
  set("maxChanges", Math.min(p.maxChanges, a.maxAdjustmentsPerWindow));
  return { params: out, tightened };
}

function actuatorReport(id: ActuatorProfileId, tightened: string[], p: GentleParams | null): ActuatorReport {
  const a = GENTLE_ACTUATOR_PROFILES[id];
  return {
    profile: id, label: a.label, existsToday: a.existsToday, midWindowAdjustment: a.midWindowAdjustment, maxAdjustmentsPerWindow: p ? p.maxChanges : a.maxAdjustmentsPerWindow,
    minDwellMin: p ? p.dwellMin : a.minDwellMin, stepW: p ? p.stepW : a.stepW, rangeW: p ? [p.minW, p.hardMaxW] : [a.minW, a.maxW], setpointUnit: a.setpointUnit,
    ownerConfirmationPerChange: a.ownerConfirmationPerChange, automaticApplyAuthorised: false, tightened, applicableNow: null, limitation: a.limitation,
  };
}

/** A safe power ceiling candidate. `watts` null / undefined / not a finite number >= 0 means UNKNOWN (never guessed). */
export interface NamedCeiling {
  name: string;
  watts: number | null | undefined;
  /**
   * Age of this value in real minutes (how long ago it was read or set). Absent or null = not tracked: a static, owner-set value is taken as
   * current (the v1 behaviour). When given, a value older than `maxCeilingAgeMin`, or an age that is not a number of minutes, is STALE (see
   * `effectiveCeiling`).
   */
  ageMin?: number | null;
  /**
   * Which side of the charger this value is measured on. Absent = already in setpoint units (an owner-set limit in the editor's own unit): never
   * converted. BATTERY_DC (a battery or BMS limit) is never raised to a grid-side equivalent: the grid-side figure would be larger by the loss, and
   * the model does not take that credit. GRID_AC (a grid-charge limit) is converted DOWN by `setpointConversionEff` unless the setpoint basis is GRID_AC.
   */
  basis?: PowerBasis;
}

/**
 * Battery-side power from a current limit and a voltage (a convenience for the two current-based ceilings); null if either is unknown. The actuator
 * turns watts into amps at the voltage the pack has when the rate is applied, so a power ceiling taken at a HIGH voltage can ask for more amps than the
 * limit allows at a lower one. Pass `minVolts`, the lowest voltage the pack can show then: the lower of the two voltages is used. A `minVolts` that is
 * not a positive number gives null (unknown), never a guess.
 */
export function powerFromCurrent(amps: number | null | undefined, volts: number | null | undefined, minVolts?: number | null): number | null {
  if (typeof amps !== "number" || typeof volts !== "number" || !Number.isFinite(amps) || !Number.isFinite(volts) || amps < 0 || volts <= 0) return null;
  if (minVolts === undefined || minVolts === null) return amps * volts;
  if (typeof minVolts !== "number" || !Number.isFinite(minVolts) || minVolts <= 0) return null;
  return amps * Math.min(volts, minVolts);
}

/** The current a power setpoint turns into at a voltage (watts / volts), never above the current limit, whatever the voltage; null if an input is unknown. */
export function ampsFromPower(watts: number | null | undefined, volts: number | null | undefined, ampLimit: number | null | undefined): number | null {
  if (typeof watts !== "number" || typeof volts !== "number" || typeof ampLimit !== "number") return null;
  if (!Number.isFinite(watts) || !Number.isFinite(volts) || !Number.isFinite(ampLimit) || watts < 0 || volts <= 0 || ampLimit < 0) return null;
  return Math.min(watts / volts, ampLimit);
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
  /** A SOC reading may be this many points BELOW the previous one before it is called implausible (a second reading is given as `previousSoc`). */
  socRegressionTolPct: number;
  /** The most the SOC may plausibly RISE per hour, in percentage points, against the previous reading (plus the resolution and the regression tolerance). */
  socJumpPctPerHour: number;
  /** Household demand safety margin on top of the peak, percent (PROVISIONAL). */
  demandMarginPct: number;
  /** Conservative demand in W used when the demand over the window is not covered and the policy is ASSUME_PROVISIONAL (PROVISIONAL, unmeasured). */
  assumedDemandW: number;
  /**
   * Percent (0-100) of the bounded solar that is credited INSIDE the hard grid limit. 0 (the default) counts no solar there: the cap is the limit minus
   * the demand peak. Anything above 0 is an explicit choice that belongs behind a MEASURED forecast skill gate (none exists today): a cloud or an
   * over-forecast takes the credited solar away within minutes and the import then crosses the known limit.
   */
  solarCreditPct: number;
  /** Household demand and solar readings older than this are stale (treated as unknown). */
  maxHouseholdAgeMin: number;
  /** Demand and solar FORECASTS older than this are stale (treated as unknown). A forecast with no valid age is unknown too. */
  maxForecastAgeMin: number;
  /**
   * Efficiency used ONLY to convert a grid-side limit (the grid headroom, a ceiling labelled GRID_AC) to the battery-side watts of a BATTERY_DC or
   * UNSETTLED setpoint: S <= efficiency x grid-side limit, so the grid import S / efficiency + demand never crosses the limit whatever the real
   * efficiency is, as long as it is not below this value. Deliberately pessimistic and UNMEASURED; 0 < eff <= 1. Not the charge-energy efficiency
   * (`chargeEff`), which only shapes the SOC projection.
   */
  setpointConversionEff: number;
  /** A named ceiling with an age (`NamedCeiling.ageMin`) older than this is stale: it cannot make a setpoint safe, but a stale lower value still caps. */
  maxCeilingAgeMin: number;
  /** A grid import limit with an age (`HouseholdInput.gridImportLimitAgeMin`) older than this is unusable (nothing is recommended). */
  maxGridLimitAgeMin: number;
  /** Slew limit: a decrease goes down by at most this much per change. At or above hardMaxW it never binds (the v1 behaviour). An increase needed for the deadline may exceed it (JUMP_FOR_DEADLINE). */
  maxDecreaseStepW: number;
  /**
   * Realised against commanded (offline evidence, one setpoint): on four recorded nights the battery-side charge power was ABOVE the commanded
   * setpoint, so a setpoint is not an upper bound of the real power. This factor (1 = off, the default) divides every cap that is converted to
   * setpoint units (a battery-side or grid-side ceiling, the grid headroom) so the REAL power stays inside it: S x factor must not exceed the limit.
   * PROVISIONAL: measured at one setpoint only; the recommended profile uses 1.1.
   */
  setpointOvershoot: number;
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
  socRegressionTolPct: 3,
  socJumpPctPerHour: 60,
  demandMarginPct: 20,
  assumedDemandW: 2000,
  solarCreditPct: 0,
  maxHouseholdAgeMin: 15,
  setpointConversionEff: 0.85,
  maxForecastAgeMin: 120,
  maxCeilingAgeMin: 60,
  maxGridLimitAgeMin: 60,
  maxDecreaseStepW: LIMITS.chargePowerMax,
  setpointOvershoot: 1,
});

/** The provisional gentle profile a caller may spread over the defaults: the slew and the overshoot allowance are OFF by default so the v1 behaviour is unchanged. */
export const GENTLE_RECOMMENDED_PARAMS: Readonly<Partial<GentleParams>> = Object.freeze({ maxDecreaseStepW: 1000, setpointOvershoot: 1.1 });

export interface GentlePolicy {
  /** What to hold when the controller cannot run (unknown or stale SOC, unknown ceiling, unusable household input). */
  fallbackPolicy: FallbackPolicy;
  /**
   * What to do when the household demand over the window is not covered by a fresh reading and a forecast. FALLBACK (the default) recommends
   * nothing: no guessed constant stands in for an unknown demand under a known safety limit. ASSUME_PROVISIONAL is an explicit option: it plans from
   * `assumedDemandW` and its status is DEGRADED, never OK.
   */
  unknownDemandPolicy: UnknownDemandPolicy;
  /** What the setpoint means to the actuator (see `SetpointBasis`). The default UNSETTLED is safe under either convention; settle it before relying on exact caps. */
  setpointBasis: SetpointBasis;
  /**
   * The ONE path a recommendation could later be applied through; its constraints (step, range, dwell, changes per window, fixed rate at the START)
   * tighten the parameters. UNCONSTRAINED (the default) assumes no path and changes nothing. Naming a path authorises nothing.
   */
  actuatorProfile: ActuatorProfileId;
}

export const DEFAULT_GENTLE_POLICY: Readonly<GentlePolicy> = Object.freeze({ fallbackPolicy: "KEEP_CURRENT", unknownDemandPolicy: "FALLBACK", setpointBasis: "UNSETTLED", actuatorProfile: "UNCONSTRAINED" });

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
  socRegressionTolPct: ["PROVISIONAL", "the measured noise and update behaviour of the SOC sensor"],
  socJumpPctPerHour: ["PROVISIONAL", "the measured fastest real charge rate of the battery"],
  demandMarginPct: ["PROVISIONAL", "the measured spread of real demand against its forecast"],
  assumedDemandW: ["MEASURED_REQUIRED", "the measured overnight household demand profile (unknown today)"],
  solarCreditPct: ["PROVISIONAL", "a measured forecast skill gate (none exists: 0 means no solar inside the hard grid limit)"],
  maxHouseholdAgeMin: ["PROVISIONAL", "the real update rate of the demand and solar sensors"],
  setpointConversionEff: ["PROVISIONAL", "the measured grid-to-battery power ratio at the settled setpoint basis (unmeasured; pessimistic by design)"],
  maxForecastAgeMin: ["PROVISIONAL", "the real refresh rate of the demand and solar forecasts"],
  maxCeilingAgeMin: ["PROVISIONAL", "the real update rate of the live battery and grid-charge limits"],
  maxGridLimitAgeMin: ["PROVISIONAL", "the real update rate of the grid import limit, when it is read from a device"],
  maxDecreaseStepW: ["PROVISIONAL", "the owner's confirmation (recommended 1000 W; off by default)"],
  fallbackPolicy: ["PROVISIONAL", "the owner's choice"],
  unknownDemandPolicy: ["PROVISIONAL", "the owner's choice"],
  setpointBasis: ["PROVISIONAL", "live proof of what the actuator's setpoint means: AC grid watts or DC battery watts"],
  actuatorProfile: ["PROVISIONAL", "the owner's decision on which one path may later apply a recommendation (none is authorised today)"],
  setpointOvershoot: ["PROVISIONAL", "commanded setpoint against measured battery-side and grid-side power at several setpoints (the saved nights hold one setpoint only, and the real power was above it)"],
  targetSocPct: ["OWNER_SET", "the owner's charge target"],
  bufferMin: ["OWNER_SET", "the owner's finish-early buffer (60 minutes when not given)"],
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
  /** Forecast demand over the remaining window. The plan uses its PEAK. It counts only with a fresh `demandProfileAgeMin`. */
  demandProfile?: readonly StepPoint[] | null;
  /** Age of the demand forecast in real minutes; null or missing counts as stale (an unknown forecast), over `maxForecastAgeMin` too. */
  demandProfileAgeMin?: number | null;
  /**
   * GROSS solar production now in W (the PV output), or null when unknown. NOT the surplus after the house: the household's own use is already in
   * `demandNowW`, so passing a surplus here would count it twice. It is bounded by the forecast and, by default, not credited to the hard limit
   * (`solarCreditPct`).
   */
  solarNowW?: number | null;
  solarAgeMin?: number | null;
  /** Forecast solar over the remaining window; counted only with a fresh reading, bounded by the reading and scaled by the confidence. */
  solarProfile?: readonly StepPoint[] | null;
  /** Age of the solar forecast in real minutes; null or missing counts as stale (the forecast is ignored). */
  solarProfileAgeMin?: number | null;
  /** 0..1; missing or invalid counts as 0 (solar not counted). Scales the forecast; it is no substitute for a measured forecast skill. */
  solarConfidence?: number | null;
  /** A KNOWN safe grid import limit in W. null or missing means unknown: no grid-headroom constraint is applied and the reason says so; it is never guessed. */
  gridImportLimitW?: number | null;
  /**
   * Age of that limit in real minutes. Missing or null = not tracked (a static, owner-set limit). When given and over `maxGridLimitAgeMin`, or not a
   * number of minutes, the limit is unusable: a limit that was given but cannot be relied on means NO recommendation (fail closed), not "no limit".
   */
  gridImportLimitAgeMin?: number | null;
}

export interface GentleInput {
  /** 10-100 (100 allowed). Never changed by the model. */
  targetSocPct: number;
  /** Finish-before-window-end buffer, 0-120 minutes in 5-minute steps. Missing = GENTLE_DEFAULT_BUFFER_MIN (60): the battery should be at the target about an hour before the window ends. */
  bufferMin?: number;
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
  /** Ordinary setpoint changes since the START in this window (the budget the START and a safety decrease do not draw on). */
  changesUsed: number;
  /**
   * EVERY recommended write since the START, the START and the safety decreases included: what a real actuator's write budget must count. Missing =
   * `changesUsed`. Counted and reported (`totalChangesUsed`), never a block: a safety decrease is never held back by a budget.
   */
  totalChangesUsed?: number;
  /** The previous accepted SOC reading and when it was taken (real minutes since the window opened), for a plausibility check; absent or null = no check. */
  previousSoc?: { socPct: number; elapsedMin: number } | null;
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
  | "JUMP_FOR_DEADLINE"
  | "SOC_IMPLAUSIBLE"
  | "SOLAR_NOT_CREDITED"
  | "FORECAST_STALE"
  | "CEILING_STALE"
  | "GRID_LIMIT_STALE"
  | "ACTUATOR_FIXED_RATE";

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
  /** The least solar CREDITED to the hard grid limit over the remaining window (W): 0 unless `solarCreditPct` is set. */
  solarCountedMinW: number | null;
  /** The least bounded solar the inputs would allow (W): information only, never inside the cap unless credited; null when not computed. */
  solarPotentialMinW: number | null;
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
  /** Every recommended write so far including this decision's, the START and safety decreases counted (see `GentleInput.totalChangesUsed`). */
  totalChangesUsed: number;
  /** True when a setpoint is in force and the model says there is nothing (more) to charge or the window is over: a STOP, which a real actuator would need a mechanism for (Free Power has no SOC stop). Informational. */
  stopRecommended: boolean;
  nextReplanInMin: number | null;
  actuationSupported: false;
  actuationReason: string;
  /** What the setpoint was taken to mean (the policy's setpointBasis): GRID_AC, BATTERY_DC or UNSETTLED (safe under either). */
  setpointBasis: SetpointBasis;
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
  /** The path this decision assumed and what it can and cannot do (see GENTLE_ACTUATOR_PROFILES). Describes constraints only; applies nothing. */
  actuator: ActuatorReport;
}

const MAX_HORIZON_MIN = 2 * 1440;
const MAX_PROFILE_POINTS = 1000;
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const ceilStep = (x: number, step: number) => Math.ceil(x / step - 1e-9) * step;
const floorStep = (x: number, step: number) => Math.floor(x / step + 1e-9) * step;
const round1 = (x: number) => Math.round(x * 10) / 10;

/**
 * The real length of the owner's wall-clock window in minutes (clock-change aware), or null for a zero-length window or an AMBIGUOUS start (exactly at
 * the change minute, or inside the hour a spring change skips): unknown, never guessed.
 */
export function windowRealMinutes(startMin: number, endMin: number, clockDay: ClockDay): number | null {
  if (!isNum(startMin) || !isNum(endMin)) return null;
  if (ambiguousClockStart(startMin, clockDay)) return null;
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

/** The capped fraction of a grid-side figure that a setpoint can use: 1 when S is grid-side watts, the conversion efficiency otherwise (UNSETTLED included). */
export function setpointScale(basis: SetpointBasis, conversionEff: number, overshoot = 1): number {
  return (basis === "GRID_AC" ? 1 : conversionEff) / overshoot;
}

/** A named ceiling in setpoint watts: only a GRID_AC (or unrecognised) label is converted, and only to a lower figure, never a higher one. */
export function ceilingInSetpointUnits(c: NamedCeiling, basis: SetpointBasis, conversionEff: number, overshoot = 1): number {
  const w = c.watts as number;
  if (c.basis === undefined || c.basis === null) return w;
  if (c.basis === "BATTERY_DC") return w / overshoot;
  return w * setpointScale(basis, conversionEff, overshoot);
}

/** True when an age is given and it is not a number of minutes from 0 to the limit (a ceiling with no age counts as current). */
function ceilingIsStale(c: NamedCeiling, maxAgeMin: number): boolean {
  return c.ageMin !== undefined && c.ageMin !== null && !fresh(c.ageMin, maxAgeMin);
}

export interface CeilingResult {
  /** The ceiling that applies (smallest known, with a fresh one present), or null when no FRESH known ceiling exists. */
  best: { watts: number; name: string } | null;
  /** The names of the known ceilings that are stale. */
  staleNames: string[];
  /** True when a stale ceiling is the one that applies because it is lower than every fresh one. */
  staleCaps: boolean;
}

/**
 * The ceiling that applies, with ages. A known ceiling is fresh unless its age is given and over `maxAgeMin` (or not a number of minutes). A stale one
 * counts as UNKNOWN for the purpose of making a setpoint safe: with no fresh known ceiling there is none (NO_SAFE_CEILING, no fallback). It is never
 * used to RAISE the cap: when a stale value is lower than every fresh one it still applies (a derated limit that went quiet is not forgotten).
 * `toSetpoint` maps a ceiling to setpoint watts (default: as given).
 */
export function effectiveCeiling(ceilings: readonly NamedCeiling[], maxAgeMin: number, toSetpoint: (c: NamedCeiling) => number = (c) => c.watts as number): CeilingResult {
  let fresh1: { watts: number; name: string } | null = null;
  let stale1: { watts: number; name: string } | null = null;
  const staleNames: string[] = [];
  for (const c of ceilings) {
    if (!c || !isNum(c.watts) || c.watts < 0) continue;
    const w = toSetpoint(c);
    if (ceilingIsStale(c, maxAgeMin)) {
      staleNames.push(String(c.name));
      if (stale1 === null || w < stale1.watts) stale1 = { watts: w, name: String(c.name) };
    } else if (fresh1 === null || w < fresh1.watts) fresh1 = { watts: w, name: String(c.name) };
  }
  if (fresh1 === null) return { best: null, staleNames, staleCaps: false };
  if (stale1 !== null && stale1.watts < fresh1.watts) return { best: stale1, staleNames, staleCaps: true };
  return { best: fresh1, staleNames, staleCaps: false };
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
      // A fractional horizon is not rounded UP: a finish that lands after it (inside the last, partial minute) is late, never on time.
      if (finish > maxMin + 1e-9) return { finishMin: null, points };
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
    if (over.setpointBasis !== undefined) out.setpointBasis = over.setpointBasis;
    if (over.actuatorProfile !== undefined) out.actuatorProfile = over.actuatorProfile;
  }
  return out;
}

function policyProblem(pol: GentlePolicy): string | null {
  if (pol.fallbackPolicy !== "KEEP_CURRENT" && pol.fallbackPolicy !== "USE_STATIC_PLAN" && pol.fallbackPolicy !== "NONE") return "fallbackPolicy must be KEEP_CURRENT, USE_STATIC_PLAN or NONE.";
  if (pol.unknownDemandPolicy !== "ASSUME_PROVISIONAL" && pol.unknownDemandPolicy !== "FALLBACK") return "unknownDemandPolicy must be ASSUME_PROVISIONAL or FALLBACK.";
  if (pol.setpointBasis !== "GRID_AC" && pol.setpointBasis !== "BATTERY_DC" && pol.setpointBasis !== "UNSETTLED") return "setpointBasis must be GRID_AC, BATTERY_DC or UNSETTLED.";
  if (!Object.prototype.hasOwnProperty.call(GENTLE_ACTUATOR_PROFILES, pol.actuatorProfile)) return "actuatorProfile must be UNCONSTRAINED, FREE_POWER_LEASE, TOU_SLOT_EDITOR or RATE_CONTROLLER_PROPOSED.";
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
  if (p.setpointConversionEff <= 0 || p.setpointConversionEff > 1) return "setpointConversionEff must be above 0 and at most 1.";
  if (p.taperStartSocPct < 0 || p.taperStartSocPct > 99) return "taperStartSocPct must be 0-99.";
  if (p.taperEndFraction <= 0 || p.taperEndFraction > 1) return "taperEndFraction must be above 0 and at most 1.";
  if (p.topHoldMin < 0 || p.topHoldMin > 120) return "topHoldMin must be 0-120 minutes.";
  if (p.demandMarginPct < 0 || p.demandMarginPct > 200) return "demandMarginPct must be 0-200.";
  if (p.assumedDemandW < 0 || p.assumedDemandW > 100000) return "assumedDemandW must be 0-100000 W.";
  if (p.solarCreditPct < 0 || p.solarCreditPct > 100) return "solarCreditPct must be 0-100.";
  if (p.maxHouseholdAgeMin <= 0 || p.maxHouseholdAgeMin > 120) return "maxHouseholdAgeMin must be 1-120 minutes.";
  if (p.maxForecastAgeMin <= 0 || p.maxForecastAgeMin > 1440) return "maxForecastAgeMin must be above 0 and at most 1440 minutes.";
  if (p.maxCeilingAgeMin <= 0 || p.maxCeilingAgeMin > 1440) return "maxCeilingAgeMin must be above 0 and at most 1440 minutes.";
  if (p.maxGridLimitAgeMin <= 0 || p.maxGridLimitAgeMin > 1440) return "maxGridLimitAgeMin must be above 0 and at most 1440 minutes.";
  if (p.maxDecreaseStepW < p.stepW) return "maxDecreaseStepW must be at least one step.";
  if (p.setpointOvershoot < 1 || p.setpointOvershoot > 1.5) return "setpointOvershoot must be 1 to 1.5 (1 = off).";
  // A slew step smaller than the hysteresis could never save the hysteresis: every slewed decrease would spend a change for less than the rule asks.
  if (p.maxDecreaseStepW < p.hardMaxW && p.maxDecreaseStepW < p.hysteresisW) return "maxDecreaseStepW must be at least hysteresisW (a slewed decrease must save the hysteresis), or leave the slew off.";
  if (p.socRegressionTolPct < 0 || p.socRegressionTolPct > 50) return "socRegressionTolPct must be 0-50.";
  if (p.socJumpPctPerHour <= 0 || p.socJumpPctPerHour > 1000) return "socJumpPctPerHour must be above 0 and at most 1000.";
  return null;
}

function inputProblem(i: GentleInput): string | null {
  if (!isNum(i.targetSocPct) || i.targetSocPct < GENTLE_BOUNDS.targetMin || i.targetSocPct > GENTLE_BOUNDS.targetMax) return "The target must be 10-100 %.";
  const bufMin = i.bufferMin === undefined ? GENTLE_DEFAULT_BUFFER_MIN : i.bufferMin;
  if (!isNum(bufMin) || bufMin < GENTLE_BOUNDS.bufferMin || bufMin > GENTLE_BOUNDS.bufferMax || bufMin % GENTLE_BOUNDS.bufferStep !== 0) return "The finish buffer must be 0-120 minutes in 5-minute steps.";
  if (!isNum(i.capacityKwh) || i.capacityKwh <= 0) return "The capacity must be a positive number of kWh.";
  if (!isNum(i.capacityUpPct) || i.capacityUpPct < 0) return "The capacity band must be a number of percent, 0 or more.";
  if (i.learnedCapacityKwh !== undefined && i.learnedCapacityKwh !== null && (!isNum(i.learnedCapacityKwh) || i.learnedCapacityKwh <= 0)) return "The learned capacity must be a positive number of kWh or null.";
  if (!isNum(i.elapsedMin) || i.elapsedMin < 0) return "The elapsed minutes must be a number, 0 or more.";
  if (!i.chargeWindow || !isNum(i.chargeWindow.startMin) || !isNum(i.chargeWindow.endMin) || !i.chargeWindow.clockDay) return "The window or the clock day is missing.";
  if (ambiguousClockStart(i.chargeWindow.startMin, i.chargeWindow.clockDay)) return "The window starts at the clock change or inside the hour the clock skips: its real length is ambiguous (unknown).";
  if (windowRealMinutes(i.chargeWindow.startMin, i.chargeWindow.endMin, i.chargeWindow.clockDay) === null) return "The window has no length.";
  if (!Array.isArray(i.ceilings)) return "The ceilings must be a list.";
  if (i.currentSetpointW !== null && (!isNum(i.currentSetpointW) || i.currentSetpointW < 0)) return "The current setpoint must be a number of watts or null.";
  if (i.lastChangeElapsedMin !== null && (!isNum(i.lastChangeElapsedMin) || i.lastChangeElapsedMin < 0 || i.lastChangeElapsedMin > i.elapsedMin)) return "The last change must be null or between the window start and now.";
  if (!Number.isInteger(i.changesUsed) || i.changesUsed < 0) return "The changes used must be a whole number, 0 or more.";
  if (i.totalChangesUsed !== undefined && (!Number.isInteger(i.totalChangesUsed) || i.totalChangesUsed < i.changesUsed)) return "The total changes used must be a whole number, at least the changes used.";
  if (i.previousSoc !== undefined && i.previousSoc !== null) {
    const q = i.previousSoc;
    if (typeof q !== "object" || !isNum(q.socPct) || q.socPct < 0 || q.socPct > 100 || !isNum(q.elapsedMin) || q.elapsedMin < 0) return "The previous SOC must be null or a reading of 0-100 % with the real minutes since the window opened.";
    if (q.elapsedMin > i.elapsedMin) return "The previous SOC reading is from after the elapsed time: the clock count went backwards.";
  }
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
    totalChangesUsed: isNum(changesUsed) ? changesUsed : 0,
    stopRecommended: false,
    nextReplanInMin: p ? p.replanMin : null,
    actuationSupported: false,
    actuationReason: ACTUATION_REASON,
    setpointBasis: "UNSETTLED",
    guarantee: "NONE",
    guaranteeNote: NO_GUARANTEE_NOTE,
    provisionalInUse: [],
    fallback: emptyFallback(policy),
    household: null,
    headroomCapW: null,
    limitedBy: "NONE",
    jumpForDeadline: false,
    actuator: actuatorReport("UNCONSTRAINED", [], null),
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
  /** The least solar CREDITED to the cap over the window (0 unless `solarCreditPct` is set). */
  solarMinW: number | null;
  /** The least bounded solar (min of the fresh reading and the confidence-scaled forecast) over the window: information only, never in the cap. */
  solarPotentialMinW: number | null;
  /** Setpoint watts per grid-side watt (1 for a GRID_AC setpoint, the conversion efficiency otherwise). */
  scale: number;
  /** The smallest per-minute headroom in setpoint watts, before rounding to a step. */
  capW: number | null;
  perMinW: number[] | null;
}

function noHousehold(): HouseholdEval {
  return { given: false, limitW: null, problem: null, codes: [], reasons: [], basis: "NONE", peakW: null, solarMinW: null, solarPotentialMinW: null, scale: 1, capW: null, perMinW: null };
}

function fresh(age: unknown, maxAge: number): boolean {
  return isNum(age) && age >= 0 && age <= maxAge;
}

/**
 * The pessimistic household evaluation over the remaining horizon: demand = the PEAK of the fresh reading and the forecast profile plus the margin
 * (an unknown demand follows the policy), solar = min(fresh reading, forecast x confidence) per minute (unknown solar counts as 0), of which only
 * `solarCreditPct` percent (0 by default) is credited to the hard limit, the grid limit = a KNOWN limit only. The per-minute headroom in setpoint watts is the battery-side headroom divided back by the efficiency; its least value is the cap.
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
  const limAge = h.gridImportLimitAgeMin;
  if (limAge !== undefined && limAge !== null && !fresh(limAge, p.maxGridLimitAgeMin)) {
    // A limit that was given but cannot be relied on is not "no limit": nothing is recommended (fail closed).
    ev.codes.push("HOUSEHOLD_UNUSABLE", "GRID_LIMIT_STALE");
    ev.problem = "The grid import limit is older than " + p.maxGridLimitAgeMin + " min or its age is not a number of minutes: it counts as unknown, and a limit that was given cannot be skipped.";
    return ev;
  }
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
    if (dp.length > 0) {
      if (fresh(h.demandProfileAgeMin, p.maxForecastAgeMin)) prof = dp;
      else {
        // A forecast with no fresh age is unknown: it does not cover the window.
        ev.codes.push("FORECAST_STALE");
        ev.reasons.push("The demand forecast is older than " + p.maxForecastAgeMin + " min or has no valid age: it counts as unknown.");
      }
    }
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
    if (stepProfileProblem(sp) === null && fresh(h.solarProfileAgeMin, p.maxForecastAgeMin)) solarProf = sp;
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
  // Solar is NOT inside the hard limit by default: a cloud or an over-forecast can take it away faster than a re-plan reacts, and the import would then
  // cross the known limit. Only the share `solarCreditPct` (0 by default, an explicit and validated parameter that belongs behind a measured forecast
  // skill gate) of the bounded solar is credited to the cap. The bounded solar is still computed and reported, labelled as information only.
  const scale = setpointScale(pol.setpointBasis, p.setpointConversionEff, p.setpointOvershoot);
  ev.scale = scale;
  const potential = solarKnown && solarProf !== null && conf > 0;
  const credit = p.solarCreditPct / 100;
  const per: number[] = [];
  let cap = Infinity;
  let solarMin = Infinity;
  let potentialMin = Infinity;
  for (let t = 0; t < n; t++) {
    const fc = potential ? stepProfileAt(solarProf as readonly StepPoint[], t) : null;
    const pot = potential ? Math.min(solarNow, (fc ?? 0) * conf) : 0;
    const s = pot * credit;
    const hr = Math.max(0, lim - peakW + s) * scale;
    per.push(hr);
    if (hr < cap) cap = hr;
    if (s < solarMin) solarMin = s;
    if (pot < potentialMin) potentialMin = pot;
  }
  if (credit === 0 && (sn !== undefined && sn !== null || sp !== undefined && sp !== null && sp.length !== 0 || sc !== undefined && sc !== null)) {
    ev.codes.push("SOLAR_NOT_CREDITED");
    ev.reasons.push("Solar is not counted inside the hard grid limit (solarCreditPct is 0, the default): it can fall faster than a re-plan reacts. The bounded solar is shown as information only.");
  }
  ev.perMinW = per;
  ev.capW = cap;
  ev.solarMinW = solarMin;
  ev.solarPotentialMinW = potentialMin;
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
function computeFallback(input: GentleInput, p: GentleParams, pol: GentlePolicy, why: string, cCeil: number | null, cMin: number, hh: HouseholdEval, toEnd: number, toDeadline: number): FallbackInfo {
  const policy = pol.fallbackPolicy;
  const after = toDeadline <= 0 && toEnd > 0 ? " The finish-early deadline has passed: this holds a rate inside the buffer, it does not plan for the deadline." : "";
  const mk = (setpointW: number | null, reason: string): FallbackInfo => ({ applied: true, policy, setpointW, reason: reason + (setpointW !== null ? after : "") });
  if (policy === "NONE") return mk(null, why + " Fallback policy NONE: no recommendation.");
  if (toEnd <= 0) return mk(null, why + " The charge window has ended: nothing is held after the window end: no recommendation.");
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
  const p0 = mergeParams(input.params);
  const pp = paramProblem(p0);
  if (pp) return fail(pp);
  const pol = mergePolicy(input.policy);
  const polProblem = policyProblem(pol);
  if (polProblem) return fail(polProblem, p0);
  // The chosen path's constraints tighten the parameters (the stricter value wins); UNCONSTRAINED changes nothing.
  const applied = applyActuatorProfile(p0, pol.actuatorProfile);
  const p = applied.params;
  const pp2 = paramProblem(p);
  if (pp2) return fail("The actuator profile " + pol.actuatorProfile + " leaves the parameters inconsistent: " + pp2, p0);
  const ip = inputProblem(input);
  if (ip) return fail(ip, p);
  const bufferMin = input.bufferMin === undefined ? GENTLE_DEFAULT_BUFFER_MIN : input.bufferMin;

  const windowReal = windowRealMinutes(input.chargeWindow.startMin, input.chargeWindow.endMin, input.chargeWindow.clockDay) as number;
  const toDeadline = windowReal - bufferMin - input.elapsedMin;
  const toEnd = windowReal - input.elapsedMin;
  const cMin = ceilStep(p.minW, p.stepW);
  const ceil = effectiveCeiling(input.ceilings, p.maxCeilingAgeMin, (c) => ceilingInSetpointUnits(c, pol.setpointBasis, p.setpointConversionEff, p.setpointOvershoot));
  const known = ceil.best;
  const cCeil = known === null ? null : floorStep(Math.min(known.watts, p.hardMaxW), p.stepW);
  const staleCeilingNote = "A named ceiling is stale (" + ceil.staleNames.join(", ") + "; older than " + p.maxCeilingAgeMin + " min or no valid age): a stale value cannot make a setpoint safe on its own" + (ceil.staleCaps ? ", and the stale value is lower than every fresh one, so it still caps" : "") + ".";
  const agedCeilings = Array.isArray(input.ceilings) && input.ceilings.some((c) => !!c && c.ageMin !== undefined && c.ageMin !== null);
  let hhMemo: HouseholdEval | null = null;
  const hhEval = (): HouseholdEval => (hhMemo ??= evalHousehold(input.household, p, pol, toEnd));
  const mk = (status: GentleStatus, reasons: string[], codes: GentleCode[]) => {
    const d = shell(status, target, reasons, codes, p, used, pol.fallbackPolicy);
    d.setpointBasis = pol.setpointBasis;
    d.actuator = actuatorReport(pol.actuatorProfile, applied.tightened, p);
    return d;
  };
  const withFallback = (d: GentleDecision, why: string, names: readonly string[]): GentleDecision => {
    d.fallback = computeFallback(input, p, pol, why, cCeil, cMin, hhEval(), toEnd, toDeadline);
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
  // A second reading, when given, must be consistent with the first: not far below it, and not further above it than a charge could carry it.
  const prevSoc = input.previousSoc;
  if (prevSoc !== undefined && prevSoc !== null) {
    const dt = input.elapsedMin - prevSoc.elapsedMin;
    const maxRise = (p.socJumpPctPerHour * dt) / 60 + p.socResolutionPct + p.socRegressionTolPct;
    if (input.socPct < prevSoc.socPct - p.socRegressionTolPct) return noData("The SOC reading (" + input.socPct + " %) is more than " + p.socRegressionTolPct + " points below the previous one (" + prevSoc.socPct + " %): implausible, nothing is recommended.", "SOC_IMPLAUSIBLE");
    if (input.socPct > prevSoc.socPct + maxRise) return noData("The SOC reading (" + input.socPct + " %) is further above the previous one (" + prevSoc.socPct + " %, " + Math.round(dt) + " min ago) than a charge could carry it: implausible, nothing is recommended.", "SOC_IMPLAUSIBLE");
  }
  const soc = input.socPct;
  if (soc >= target) {
    // A reported reading at or above the target counts as reached (the pessimistic offset applies to the plan only); a setpoint in force then needs a STOP.
    const d = mk("NOTHING_TO_CHARGE", ["The battery is at " + soc + " %, at or above the " + target + " % target."], ["AT_TARGET"]);
    d.stopRecommended = isNum(input.currentSetpointW) && input.currentSetpointW > 0;
    d.provisionalInUse = provisionalList(["maxSocAgeMin"], p, pol, input);
    return d;
  }

  // The safe ceiling: the smallest KNOWN one, rounded down to a step, capped at the editor maximum. None known = no recommendation.
  if (known === null || cCeil === null) {
    const none = mk("NO_SAFE_CEILING", ["No safe power ceiling is known (owner maximum, battery maximum charge power, grid-charge power); no default is guessed and nothing is recommended."], ["NO_CEILING"]);
    if (ceil.staleNames.length > 0) {
      none.codes.push("CEILING_STALE");
      none.reasons.push(staleCeilingNote + " No fresh known ceiling remains.");
    }
    return withFallback(none, "No safe ceiling is known.", agedCeilings ? ["maxCeilingAgeMin"] : []);
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
  const householdNames: string[] = hh.given && hh.limitW !== null ? ["demandMarginPct", "maxHouseholdAgeMin", "maxForecastAgeMin", "setpointBasis", ...(pol.setpointBasis !== "GRID_AC" ? ["setpointConversionEff"] : []), ...(hh.basis === "ASSUMED" ? ["assumedDemandW", "unknownDemandPolicy"] : [])] : [];
  const hold = target >= 100 ? p.topHoldMin : 0;
  const slewNames = p.maxDecreaseStepW < p.hardMaxW ? ["maxDecreaseStepW"] : [];
  const provNames = [...CORE_NAMES, ...(hold > 0 ? ["topHoldMin"] : []), ...(agedCeilings ? ["maxCeilingAgeMin"] : []), ...householdNames, ...slewNames];
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
  const totalUsed = isNum(input.totalChangesUsed) ? input.totalChangesUsed : used;

  const out = mk("OK", [], []);
  out.ceilingW = cMax0;
  out.ceilingName = known.name;
  out.totalChangesUsed = totalUsed;
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
    if (ceil.staleNames.length > 0) {
      out.codes.push("CEILING_STALE");
      out.reasons.push(staleCeilingNote);
    }
    if (hh.given) {
      out.codes.push(...hh.codes);
      out.reasons.push(...hh.reasons);
      if (hh.limitW !== null) {
        if (headroomBinds) {
          out.codes.push("HEADROOM_LIMITED");
          out.reasons.push(summary());
        }
        // the grid import this setpoint would draw if the setpoint is battery-side (S / scale), which is the larger reading under UNSETTLED
        const imp = out.setpointW === null ? null : gridImportW(out.setpointW, hh.scale, hh.peakW as number, hh.solarMinW as number);
        out.household = householdReport(hh, imp, p, headroomBinds ? "The grid headroom limits the setpoint." : "The grid headroom does not bind.");
      } else out.household = householdReport(hh, null, p, "No grid limit is known: no headroom constraint.");
      if (out.status === "OK" && hh.basis === "ASSUMED") {
        // A plan that rests on an assumed demand under a known safety limit is not a normal OK.
        out.status = "DEGRADED";
        out.reasons.push("Status DEGRADED, not OK: the grid cap rests on the provisional assumed demand (assumed, not measured), not on a forecast or a fresh reading.");
      }
      if (out.status === "TARGET_AT_RISK" || out.status === "TARGET_UNREACHABLE") out.reasons.push("The target is NOT guaranteed.");
    }
    if ((out.status === "TARGET_AT_RISK" || out.status === "TARGET_UNREACHABLE") && !out.actuator.midWindowAdjustment) {
      // With the rate fixed at the START nothing inside the window can repair a shortfall; the model says so instead of implying a later correction.
      if (!out.codes.includes("ACTUATOR_FIXED_RATE")) out.codes.push("ACTUATOR_FIXED_RATE");
      out.reasons.push("On this path the rate is fixed at the START, so a shortfall cannot be corrected inside the window: the choices are a larger buffer, an earlier start or the owner's own override. The recommended START rate is the highest safe one, never a lower target.");
    }
    return out;
  };
  // The lowest step whose forward simulation reaches the target by the deadline (finish time is monotone in the setpoint). With a `lead`, the first
  // `lead.min` minutes run at `lead.w` instead of the step searched for (a raise that waits out the dwell).
  const avail = toDeadline - hold;
  const lowestStep = (within: number, lead?: { w: number; min: number }): number | null => {
    const fin = (w: number): number | null => (lead === undefined ? finish(w, within) : projectCharge(planSoc, w, target, { ...model, leadW: lead.w, leadMin: lead.min }, within)).finishMin;
    if (within <= 0 || fin(cMax) === null) return null;
    let lo = cMin;
    let hi = cMax;
    while (lo < hi) {
      const mid = lo + floorStep((hi - lo) / 2, p.stepW);
      if (fin(mid) !== null) hi = mid;
      else lo = mid + p.stepW;
    }
    return lo;
  };
  const finalise = (c: Choice) => {
    out.setpointW = c.w;
    out.change = c.change;
    out.changeRecommended = c.change !== "NONE";
    out.codes.push(c.code);
    if (c.extra) out.codes.push(...c.extra);
    out.jumpForDeadline = c.extra !== undefined && c.extra.includes("JUMP_FOR_DEADLINE");
    out.reasons.push(c.reason);
    if (c.change !== "NONE") {
      // A fixed-rate path can set the rate at the START only: a later change (in practice a safety decrease) cannot be applied on it, and a stop is the safe action.
      const fixed = c.change !== "START" && !out.actuator.midWindowAdjustment;
      out.actuator.applicableNow = !fixed;
      if (fixed) {
        out.codes.push("ACTUATOR_FIXED_RATE");
        out.reasons.push("This path fixes the rate at the START: the change to " + c.w + " W cannot be applied on it. Keep the rate only if it is safe; otherwise stop. A stop is recommended here.");
        out.stopRecommended = true;
      }
    }
    // The START and a safety decrease do not draw on the budget; an ordinary increase or decrease does.
    out.changesUsed = used + (c.change === "INCREASE" || c.code === "DECREASE_SAVING" ? 1 : 0);
    out.changesLeft = Math.max(0, p.maxChanges - out.changesUsed);
    // The write count a real actuator must keep: every recommended change, the START and a safety decrease included (never a block).
    out.totalChangesUsed = totalUsed + (c.change !== "NONE" ? 1 : 0);
    // A hold that waits out the dwell projects the raise the model will actually make afterwards: the LOWEST step that still makes the deadline, not the
    // ceiling, so the margin shown is the one the later raise gives (about none), never the larger one a raise to the ceiling would give.
    const pr = c.lead
      ? projectCharge(planSoc, lowestStep(avail, c.lead) ?? cMax, target, { ...model, leadW: c.lead.w, leadMin: c.lead.min }, Math.max(toEnd - hold, 0), 5)
      : finish(c.w, Math.max(toEnd - hold, 0), 5);
    out.finishInMin = pr.finishMin === null ? null : round1(pr.finishMin);
    out.marginMin = pr.finishMin === null ? null : round1(toDeadline - hold - pr.finishMin);
    out.trajectory = pr.points;
    return pr;
  };

  if (toDeadline <= 0) {
    out.status = "DEADLINE_PASSED";
    out.codes.push("DEADLINE_PASSED");
    out.reasons.push(bufferMin >= windowReal ? "The finish-early buffer (" + bufferMin + " min) is as long as the " + windowReal + " min window: the deadline is not after the window opens. The target is not lowered." : "The finish-early deadline has passed with the battery at " + soc + " % (target " + target + " %). The target is not lowered.");
    if (bufferMin >= windowReal) out.codes.push("BUFFER_AS_LONG_AS_WINDOW");
    if (toEnd > 0) {
      const c = choose(cMax, cMax, cMax, cur, sinceChange, budgetLeft, p, ctx(true));
      finalise(c);
      out.reasons.push("Time is left before the window ends: the " + (headroomBinds ? "safe grid headroom" : "ceiling") + " is the best effort.");
    } else out.stopRecommended = isNum(cur) && cur > 0;
    return done();
  }

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
        const nb = bufferMin - ceilStep(lateBy, GENTLE_BOUNDS.bufferStep);
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
    solarPotentialMinW: hh.solarPotentialMinW === null ? null : round1(hh.solarPotentialMinW),
    projectedImportW: importW === null ? null : round1(importW),
    note: note + (hh.basis === "ASSUMED" ? " Demand is the provisional assumption of " + p.assumedDemandW + " W at least." : ""),
  };
}
