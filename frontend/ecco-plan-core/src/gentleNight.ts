// Gentle Smart Charging, the NIGHT planner (read only, offline, unreleased): `planGentleNight(input)` answers, from the readings given, "what is the
// gentlest charge rate that still reaches the target SOC by the deadline, how would the night run, and how sure is that?". Pure data in, data out: no I/O,
// no clock, no class, no state between calls. It is NOT exported by the package index (the Energy Actions card bundle is pinned and would change).
//
// What it returns: the recommended setpoint for NOW, a planned TRAJECTORY of timed setpoints (100 W steps, never below 500 W, never above the ceiling,
// inside the selected actuator profile's change budget and dwell), the expected finish, the SOC at the deadline as a pessimistic / expected / optimistic
// band, one status, reason codes, and what would be needed to apply it. It NEVER applies anything: `actuationSupported` is always false.
//
// How it decides (every number is a parameter, see DEFAULT_NIGHT_PARAMS):
//  * Window and deadline come from the slot-table times (wall clock). The deadline is the window end minus the buffer (default 60, 0 to 120 in steps of 5).
//    A night on which the wall clock skips or repeats an hour inside the window is REFUSED (the real length is not known), like the R9 schedule packages.
//  * Battery model: an explicit measured-SHAPE taper, not a slope: a flat plateau up to a knee SOC, then a fast fall (within a few minutes) to a low tail.
//    The tail power is anchored to the plateau power AT THE KNEE (a later raise of the setpoint is never credited). Three worlds are simulated: the
//    PESSIMISTIC one (earlier knee, lower tail, cliff, larger capacity, lower efficiency, a lower start) decides the rate; the expected and optimistic
//    ones only describe the band. The knee SOC is NOT KNOWN (no SOC series was saved): the default pessimistic knee is a configurable 90.
//    Whether the battery may already be past the knee is decided from the reading's OPTIMISTIC estimate (reading + resolution/2 + noise): when it is at or
//    past the pessimistic knee (and the target is above it) the pessimistic world starts on the tail, anchored at the lower of the rate in force and the
//    rate tried, and a rate in force is held (a raise inside the reading uncertainty is never credited).
//  * Rate: the lowest 100 W step (not below 500 W) whose PESSIMISTIC simulation reaches the target by the deadline, from the measured SOC. When none does,
//    the highest safe rate, status TARGET_AT_RISK (inside the buffer) or UNREACHABLE; the target is never lowered.
//  * Status OK never relies on a later change: no path makes one by itself (each needs the owner, or the path does not exist), so OK is judged with the
//    first rate HELD for the rest of the window; when only a planned later change makes the deadline the status is TARGET_AT_RISK (RELIES_ON_LATER_CHANGE).
//  * Adaptation is honest: the trajectory is the closed-loop policy run on the expected world (re-plan from the measured SOC at each dwell interval,
//    a change only when the profile's change budget and dwell allow it). Only the RATE_CONTROLLER_PROPOSED path (does not exist) and the unconstrained
//    generic model can change a rate several times; TOU_SLOT_EDITOR allows at most one coarse, owner-confirmed change; FREE_POWER_LEASE none (a rate in
//    force above the ceiling on it gives STOP_RECOMMENDED, never a change). Every point after the first is `conditional`: it is re-computed from the
//    measured SOC when the time comes. With no profile named, the most restrictive path that exists (FREE_POWER_LEASE) is assumed and said.
//  * Unknown data is never guessed: stale or unknown SOC, capacity or limits give INPUTS_UNUSABLE. A KNOWN grid import limit with an unknown or stale
//    demand also gives INPUTS_UNUSABLE; an UNKNOWN grid import limit applies no cap and says so (GRID_LIMIT_UNKNOWN_NO_CAP). Before the window a bound
//    on the battery drain until it opens is required (the SOC at the window start is otherwise not known). A rate in force of 0 W is "not charging"
//    (a START); one below the minimum or off the step (at or below the ceiling) is refused.
import { ACTUATION_REASON, CONTROLLER_LABEL, DEFAULT_GENTLE_PARAMS, GENTLE_ACTUATOR_PROFILES, applyActuatorProfile, ceilingInSetpointUnits, effectiveCeiling, windowRealMinutes } from "./gentleController.ts";
import type { ActuatorProfileId, NamedCeiling } from "./gentleController.ts";
import { fmt, norm, span } from "./time.ts";
import type { ClockDay } from "./time.ts";
import { LIMITS } from "./settings.ts";
import type { NativeSlot } from "./tou.ts";

export type NightStatus = "OK" | "TARGET_AT_RISK" | "UNREACHABLE" | "STOP_RECOMMENDED" | "NO_NEED" | "INPUTS_UNUSABLE" | "CLOCK_CHANGE_NIGHT_REFUSED";
export type NightChange = "START" | "KEEP" | "INCREASE" | "DECREASE" | "STOP" | "NONE";

/** Every reason code the night planner can return (a closed list; the tests pin that nothing else is ever returned). */
export const NIGHT_CODES = [
  "TARGET_INVALID", "BUFFER_INVALID", "WINDOW_INVALID", "CLOCK_DAY_INVALID", "ELAPSED_INVALID", "WINDOW_OVER", "NO_SOC", "STALE_SOC", "SOC_IMPLAUSIBLE",
  "CAPACITY_UNUSABLE", "PARAMS_INVALID", "PROFILE_INVALID", "INPUT_INVALID", "NO_SAFE_CEILING", "CEILING_BELOW_MIN", "HEADROOM_BELOW_MIN", "GRID_LIMIT_STALE",
  "DEMAND_UNKNOWN", "CLOCK_CHANGE_NIGHT", "AT_TARGET", "RATE_GENTLEST", "RATE_AT_MINIMUM", "RATE_AT_CEILING", "START", "INCREASE_NEEDED", "DECREASE_SAVES",
  "HELD_DWELL", "HELD_BUDGET", "HELD_PATH_FIXED", "HELD_PAST_KNEE", "FORCED_BELOW_CEILING", "TARGET_ABOVE_KNEE", "TOP_OF_CHARGE_TAIL", "GRID_LIMIT_UNKNOWN_NO_CAP",
  "CEILING_AGE_UNKNOWN", "BEFORE_WINDOW", "DEADLINE_PASSED_WINDOW_OPEN", "RATE_NOT_ENOUGH_ALONE", "PESSIMISTIC_MISSES_DEADLINE", "RELIES_ON_LATER_CHANGE", "SETPOINT_UNIT_UNSETTLED",
  "ACTUATOR_FIXED_RATE", "IN_FORCE_INVALID", "IN_FORCE_ZERO_NOT_CHARGING", "PRE_WINDOW_DRAIN_UNKNOWN", "PROFILE_DEFAULT_MOST_RESTRICTIVE",
] as const;
export type NightCode = (typeof NIGHT_CODES)[number];

export interface GentleNightParams {
  /** Setpoint granularity in W (the editor's 100 W step). */
  stepW: number;
  /** Lowest recommendable setpoint (the editor's 500 W). */
  minW: number;
  /** The firmware setpoint bound; never above LIMITS.chargePowerMax. */
  hardMaxW: number;
  /** Realised power against commanded (owner decision, 1.0 to 1.5): divides every limit converted to setpoint units. */
  setpointOvershoot: number;
  /** The usable capacity may be this much above and below the trusted figure, percent. */
  capacityBandPct: number;
  /** Grid-to-battery efficiency: the expected figure and the pessimistic / optimistic ends of its band. */
  chargeEff: number;
  chargeEffMin: number;
  chargeEffMax: number;
  /** The SOC sensor's scale error, percent (a reported change of 1 point may be 1/(1 - s) true points). */
  socScaleErrPct: number;
  /** Resolution of the SOC reading in points, and the noise allowance in points: the pessimistic start is the reading minus half the resolution minus the noise. */
  socResolutionPct: number;
  socNoisePct: number;
  /** The PESSIMISTIC knee SOC (an earlier knee is more pessimistic): the plateau ends here. Not measured; configurable. */
  kneeSocPct: number;
  /** The expected knee is this many points above the pessimistic one, the optimistic one twice this (at most 99.5). */
  kneeSpreadPct: number;
  /** Tail power as a fraction of the plateau power at the knee: pessimistic, expected, optimistic (saved nights: about 1/8 to 1/3 after about 5 minutes). */
  tailFraction: number;
  tailFractionExpected: number;
  tailFractionOptimistic: number;
  /** Minutes the fall from the plateau to the tail takes in the expected and optimistic worlds (the pessimistic world falls in at most one minute). */
  dropMin: number;
  /** Readings older than this are stale; limits and household readings likewise. */
  maxSocAgeMin: number;
  maxCeilingAgeMin: number;
  maxHouseholdAgeMin: number;
  maxGridLimitAgeMin: number;
  /** Grid-side to setpoint conversion and the demand margin, for the grid headroom cap (only when a grid import limit AND a fresh demand are known). */
  setpointConversionEff: number;
  demandMarginPct: number;
  /** A decrease is planned only when it saves at least this much, and only when the plan keeps this many minutes of slack to the deadline. */
  hysteresisW: number;
  decreaseSlackMin: number;
  /** Re-plan interval the caller should use, and the change constraints (a profile only tightens them). */
  replanMin: number;
  dwellMin: number;
  maxChanges: number;
  /** A SOC reading may be this many points below the previous one, or rise this many points per hour more than plausible, before it is implausible. */
  socRegressionTolPct: number;
  socJumpPctPerHour: number;
}

export const DEFAULT_NIGHT_PARAMS: Readonly<GentleNightParams> = Object.freeze({
  stepW: 100, minW: LIMITS.chargePowerMin, hardMaxW: LIMITS.chargePowerMax, setpointOvershoot: 1.1, capacityBandPct: 6,
  chargeEff: 0.95, chargeEffMin: 0.9, chargeEffMax: 0.97, socScaleErrPct: 3, socResolutionPct: 1, socNoisePct: 0.5,
  kneeSocPct: 90, kneeSpreadPct: 5, tailFraction: 0.125, tailFractionExpected: 0.2, tailFractionOptimistic: 0.33, dropMin: 5,
  maxSocAgeMin: 15, maxCeilingAgeMin: 60, maxHouseholdAgeMin: 15, maxGridLimitAgeMin: 60, setpointConversionEff: 0.85, demandMarginPct: 20,
  hysteresisW: 500, decreaseSlackMin: 15, replanMin: 10, dwellMin: 30, maxChanges: 6, socRegressionTolPct: 3, socJumpPctPerHour: 60,
});

const BOUNDS: Readonly<Record<keyof GentleNightParams, readonly [number, number]>> = Object.freeze({
  stepW: [1, 1000], minW: [100, 8000], hardMaxW: [500, LIMITS.chargePowerMax], setpointOvershoot: [1, 1.5], capacityBandPct: [0, 20], chargeEff: [0.5, 1], chargeEffMin: [0.5, 1],
  chargeEffMax: [0.5, 1], socScaleErrPct: [0, 10], socResolutionPct: [0.1, 5], socNoisePct: [0, 5], kneeSocPct: [50, 100], kneeSpreadPct: [0, 20], tailFraction: [0, 1],
  tailFractionExpected: [0, 1], tailFractionOptimistic: [0, 1], dropMin: [0, 30], maxSocAgeMin: [1, 120], maxCeilingAgeMin: [1, 1440], maxHouseholdAgeMin: [1, 240],
  maxGridLimitAgeMin: [1, 1440], setpointConversionEff: [0.1, 1], demandMarginPct: [0, 200], hysteresisW: [0, 4000], decreaseSlackMin: [0, 120], replanMin: [5, 15],
  dwellMin: [0, 240], maxChanges: [0, 20], socRegressionTolPct: [0, 10], socJumpPctPerHour: [10, 200],
});

export interface NightHousehold {
  /** A KNOWN safe grid import limit in W. null or missing = unknown: no cap, and the plan says so. */
  gridImportLimitW?: number | null;
  gridImportLimitAgeMin?: number | null;
  /** The household demand peak over the rest of the window in W (excluding the charger). Needed whenever a grid limit is known; never guessed. */
  demandPeakW?: number | null;
  demandAgeMin?: number | null;
}

/** What is in force now (the caller's own record). `lastChangeAtMin` is real minutes since the window opened (negative before it). */
export interface NightInForce {
  setpointW: number | null;
  lastChangeAtMin: number | null;
  /** Ordinary changes since the START (the START and a forced decrease below the ceiling do not count). */
  changesUsed: number;
}

export interface GentleNightInput {
  targetSocPct: number;
  /** Finish-early buffer, 0 to 120 in steps of 5; missing = 60. */
  bufferMin?: number;
  /** The charge window from the slot table, in wall-clock minutes, and the clock day it falls on. */
  chargeWindow: { startMin: number; endMin: number };
  clockDay: ClockDay;
  /** Real minutes since the window opened; negative before it (the plan then starts at the window start). */
  elapsedMin: number;
  /**
   * Required before the window opens (elapsedMin < 0): a PESSIMISTIC (high) bound on the battery's net discharge in W, battery side, from the moment of
   * the reading until the window opens (the house load not covered by solar, divided by the discharge efficiency). The SOC at the window start is then
   * the reading less this drain over the reading's age plus the time to the window, counted in the most points per kWh the bands allow. Missing before
   * the window: PRE_WINDOW_DRAIN_UNKNOWN (never guessed). Ignored once the window is open.
   */
  preWindowDrainW?: number | null;
  socPct: number | null;
  socAgeMin: number | null;
  previousSoc?: { socPct: number; elapsedMin: number } | null;
  capacityKwh: number | null;
  learnedCapacityKwh?: number | null;
  /** The safe power ceilings that are known (at least the firmware bound and the owner limit as one named ceiling, see maxChargePowerCeiling). */
  ceilings: readonly NamedCeiling[];
  household?: NightHousehold;
  /** What is in force now. A setpoint of 0 W is "not charging" (the recommendation is a START); one above 0 W but below the minimum or off the step is refused. */
  inForce?: NightInForce | null;
  /** The path a recommendation would be applied on. Missing: FREE_POWER_LEASE, the most restrictive path that exists (PROFILE_DEFAULT_MOST_RESTRICTIVE). */
  actuatorProfile?: ActuatorProfileId;
  params?: Partial<GentleNightParams>;
}

export interface TrajectoryPoint {
  /** Real minutes since the window opened, and from now. */
  atMin: number;
  inMin: number;
  setpointW: number;
  change: NightChange;
  /** True for every point after the first: re-computed from the measured SOC when its time comes, never a commitment. */
  conditional: boolean;
}

export interface WorldOutcome {
  /** Real minutes since the window opened at which the target is reached, or null when not within the window. */
  finishMin: number | null;
  /** SOC (reading scale) at the deadline under the trajectory; the target once reached (the charge stops there). */
  socAtDeadlinePct: number;
  reachedByDeadline: boolean;
}

export interface NightProfileReport {
  id: ActuatorProfileId;
  label: string;
  existsToday: boolean;
  maxChanges: number;
  changesLeft: number;
  dwellMin: number;
  midWindowAdjustment: boolean;
  ownerConfirmationPerChange: boolean;
  /** Plainly: whether the trajectory can really adapt on this path. */
  adaptive: boolean;
  adaptiveNote: string;
}

export interface GentleNightPlan {
  label: typeof CONTROLLER_LABEL;
  status: NightStatus;
  codes: NightCode[];
  reasons: string[];
  targetSocPct: number | null;
  bufferMin: number | null;
  windowRealMin: number | null;
  deadlineMin: number | null;
  deadlineInMin: number | null;
  /** The recommendation for NOW; null setpoint when there is none. */
  now: { setpointW: number | null; change: NightChange; neededW: number | null; neededMeetsDeadline: boolean | null; ceilingW: number | null; ceilingName: string | null; minW: number; stepW: number };
  trajectory: TrajectoryPoint[];
  expectedFinish: { atMin: number; inMin: number; wallClock: string } | null;
  /**
   * The three worlds under the policy (with its conditional later changes), and the pessimistic world with the first rate HELD for the rest of the
   * window: the status, the margin and the buffer that would fit are judged on `pessimisticHeld` (no path makes a later change by itself). After a STOP
   * recommendation every world is the rate in force held (what happens if nothing is done).
   */
  band: { pessimistic: WorldOutcome; expected: WorldOutcome; optimistic: WorldOutcome; pessimisticHeld: WorldOutcome } | null;
  /** Minutes the pessimistic world with the first rate held finishes before the deadline (negative: after it); null when it does not finish in the window. */
  marginMin: number | null;
  /** The largest buffer (a multiple of 5) with which the pessimistic world with the first rate held would still finish in the window; null when none does. */
  bufferThatWouldFitMin: number | null;
  /** True only with STOP_RECOMMENDED: the rate in force is above the safe ceiling on a path that cannot lower it. */
  stopRecommended: boolean;
  profile: NightProfileReport | null;
  /** What would be needed to apply the recommendation (nothing here applies it). */
  needed: string[];
  /** What is not known and the plan cannot know. */
  unknowns: string[];
  assumptions: Record<string, number> | null;
  actuationSupported: false;
  actuationReason: string;
  guarantee: "NONE";
  guaranteeNote: string;
}

export const NIGHT_GUARANTEE_NOTE =
  "The target is NOT guaranteed. The plan assumes a plateau-then-fall battery shape whose knee SOC is unknown, a capacity band, an efficiency band and a sensor scale band; a real battery outside them can miss. It is read-only: it recommends and applies nothing.";

const CODE_TEXT: Readonly<Record<NightCode, string>> = Object.freeze({
  TARGET_INVALID: "The target SOC is missing or outside 10 to 100.",
  BUFFER_INVALID: "The buffer is not a multiple of 5 from 0 to 120.",
  WINDOW_INVALID: "The charge window is missing, has no length, or its times are not minutes of the day.",
  CLOCK_DAY_INVALID: "The clock-day description is not valid.",
  ELAPSED_INVALID: "The elapsed time is not a number of minutes (at most 12 hours before the window).",
  WINDOW_OVER: "The charge window is over: nothing is planned.",
  NO_SOC: "The SOC is unknown: nothing is recommended.",
  STALE_SOC: "The SOC reading is older than the limit: nothing is recommended.",
  SOC_IMPLAUSIBLE: "The SOC reading is outside 0 to 100 or jumps against the previous one: nothing is recommended.",
  CAPACITY_UNUSABLE: "The usable capacity is unknown or not a positive number: nothing is recommended.",
  PARAMS_INVALID: "A parameter is not a number inside its bounds.",
  PROFILE_INVALID: "The actuator profile is not one of the four known paths.",
  INPUT_INVALID: "The input is not a valid object.",
  NO_SAFE_CEILING: "No fresh known safe power ceiling: nothing is recommended (a ceiling is never guessed).",
  CEILING_BELOW_MIN: "The safe ceiling is below the lowest setpoint: nothing can be recommended.",
  HEADROOM_BELOW_MIN: "The grid headroom is below the lowest setpoint: nothing can be recommended.",
  GRID_LIMIT_STALE: "The grid import limit is older than the limit: nothing is recommended.",
  DEMAND_UNKNOWN: "A grid import limit is known but the household demand is unknown or stale: nothing is recommended (demand is never guessed).",
  CLOCK_CHANGE_NIGHT: "The window touches a clock change: the real length is not known, so no plan is made (refused, like the schedule packages).",
  AT_TARGET: "The battery reading is at or above the target: nothing to charge.",
  RATE_GENTLEST: "The lowest rate whose pessimistic simulation reaches the target by the deadline.",
  RATE_AT_MINIMUM: "The practical minimum already reaches the target by the deadline.",
  RATE_AT_CEILING: "Only the highest safe rate gives the best chance: nothing gentler reaches the target by the deadline in the pessimistic simulation.",
  START: "No rate is in force: this is the rate to start with.",
  INCREASE_NEEDED: "The rate in force would miss the deadline in the pessimistic simulation: a higher rate is recommended.",
  DECREASE_SAVES: "The battery is ahead of the pessimistic plan: a lower rate still makes the deadline with the slack and saves at least the hysteresis.",
  HELD_DWELL: "A change is recommended but the path's minimum time since the last change has not passed: the rate in force stays for now.",
  HELD_BUDGET: "A change is recommended but the path's changes for this window are used up: the rate in force stays.",
  HELD_PATH_FIXED: "A change is recommended but this path cannot change a rate after the start: the rate in force stays.",
  HELD_PAST_KNEE: "The battery may be past the pessimistic knee (the reading's optimistic estimate is at or past it): the BMS sets the power there, a lower setpoint can only slow it and a higher one is not credited, so the rate in force is held.",
  FORCED_BELOW_CEILING: "The rate in force is above the safe ceiling: it must come down to the ceiling whatever the budget and dwell say.",
  TARGET_ABOVE_KNEE: "The target is above the pessimistic knee, where the charge power falls to a low tail: it takes much longer and is the most at risk.",
  TOP_OF_CHARGE_TAIL: "At a 100 % target the battery may keep charging for a while after the reading reaches 100; stopping at the first 100 would cut it off.",
  GRID_LIMIT_UNKNOWN_NO_CAP: "The grid import limit is unknown, so no grid cap is applied (the plan does not know it would be crossed).",
  CEILING_AGE_UNKNOWN: "A safe ceiling came with no age and is taken as current.",
  BEFORE_WINDOW: "The window has not opened: the plan starts at the window start from the reading less the given drain bound over the reading's age and the time to the window.",
  DEADLINE_PASSED_WINDOW_OPEN: "The deadline has passed but the window is still open: best effort only.",
  RATE_NOT_ENOUGH_ALONE: "The expected world reaches the deadline but the pessimistic world does not.",
  PESSIMISTIC_MISSES_DEADLINE: "The pessimistic simulation misses the deadline at the highest safe rate.",
  RELIES_ON_LATER_CHANGE: "The pessimistic world only makes the deadline with a planned later change, and no path makes one by itself (each needs the owner, or the path does not exist): judged with the first rate held, the status is not OK.",
  SETPOINT_UNIT_UNSETTLED: "What the setpoint means (AC grid watts, DC battery watts or amps) is not established: the plan treats it as grid-side watts for energy and applies the overshoot allowance to converted limits.",
  ACTUATOR_FIXED_RATE: "This path fixes the rate at the START: the rate in force cannot be lowered to the ceiling, so a STOP is recommended; the status and the band are for the rate in force.",
  IN_FORCE_INVALID: "The rate in force is above 0 W but below the minimum or off the step (and not above the ceiling): it is not a setpoint this path can hold, so nothing is recommended.",
  IN_FORCE_ZERO_NOT_CHARGING: "The rate in force is 0 W: taken as not charging, so the recommendation is a START (the change count given is kept).",
  PRE_WINDOW_DRAIN_UNKNOWN: "The window has not opened and no bound on the battery drain until it opens was given: the SOC at the window start is not known, so nothing is recommended (never guessed).",
  PROFILE_DEFAULT_MOST_RESTRICTIVE: "No actuator path was named: the most restrictive path that exists (the Free Power start, one fixed rate) is assumed.",
});

const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const ceilStep = (x: number, step: number): number => Math.ceil(x / step - 1e-9) * step;
const floorStep = (x: number, step: number): number => Math.floor(x / step + 1e-9) * step;
const EPS = 1e-9;

// ---- the slot table to the window ---------------------------------------------------------------------------------------------------------------

/**
 * The charge window of a native slot table: the one run of consecutive Grid-source slots (wall-clock start of the first, start of the slot after the run),
 * with the power and target of the run. null when there is no Grid slot, more than one separate run, the run covers the whole table, or the slots of the
 * run disagree on power or target (ambiguous: never guessed).
 */
export function windowFromSlotTable(slots: readonly NativeSlot[]): { startMin: number; endMin: number; powerW: number; targetSoc: number } | null {
  if (!Array.isArray(slots) || slots.length < 2) return null;
  const sorted = [...slots].filter((s) => s !== null && typeof s === "object" && isNum(s.startMin)).sort((a, b) => a.startMin - b.startMin);
  const n = sorted.length;
  if (n !== slots.length) return null;
  const isGrid = sorted.map((s) => s.source === "Grid");
  const gridCount = isGrid.filter((g) => g).length;
  if (gridCount === 0 || gridCount === n) return null;
  let runStarts = 0;
  let first = -1;
  for (let i = 0; i < n; i++) {
    if (isGrid[i] && !isGrid[(i + n - 1) % n]) {
      runStarts++;
      first = i;
    }
  }
  if (runStarts !== 1) return null;
  const run: NativeSlot[] = [];
  let i = first;
  while (isGrid[i % n]) {
    run.push(sorted[i % n] as NativeSlot);
    i++;
  }
  const head = run[0] as NativeSlot;
  if (run.some((s) => s.powerW !== head.powerW || s.targetSoc !== head.targetSoc)) return null;
  const after = sorted[i % n] as NativeSlot;
  return { startMin: head.startMin, endMin: after.startMin, powerW: head.powerW, targetSoc: head.targetSoc };
}

/** True when the wall-clock window overlaps the hour a clock change skips or repeats (edges included): its real length would not be known. */
export function windowTouchesClockChange(startMin: number, endMin: number, day: ClockDay): boolean {
  if (day.deltaMin === 0) return false;
  const wall = span(startMin, endMin);
  const rangeStart = norm(day.changeAtMin - 60);
  return span(rangeStart, startMin) <= 120 || span(startMin, rangeStart) <= wall;
}

// ---- the battery model (the controller's own, explicit shape) -------------------------------------------------------------------------------------

interface World {
  name: "pessimistic" | "expected" | "optimistic";
  /** kWh per percent of the reading scale. */
  pctKwh: number;
  eff: number;
  knee: number;
  tail: number;
  dropMin: number;
  /** The world's true position in the reading scale relative to the displayed reading. */
  offset: number;
}

interface SimState {
  t: number;
  soc: number;
  kneeAt: number | null;
  kneeW: number | null;
}

/**
 * Whether the battery may already be past the PESSIMISTIC knee: the reading's OPTIMISTIC estimate (reading + resolution/2 + noise) is at or past it. Only
 * a target above the knee counts: inside the envelope a target at or below the pessimistic knee is reached on the plateau.
 */
function kneeMayBePassed(c: Ctx, reading: number): boolean {
  return c.target > c.pess.knee + EPS && reading + c.upOffset >= c.pess.knee - EPS;
}

/**
 * The simulation start of world `w` from a displayed reading, with `rateW` the rate simulated and `inForceW` the rate in force (null: none). The
 * PESSIMISTIC world starts past its knee (on the tail, the fall over) whenever the knee may already be passed, with the tail anchored at the LOWER of the
 * rate in force and the rate simulated: a raise inside the reading uncertainty is never credited. The other worlds start past their own knee only from
 * their own position, anchored at the rate in force (or the rate simulated when none is in force).
 */
function startState(c: Ctx, w: World, t: number, reading: number, inForceW: number | null, rateW: number): SimState {
  const soc = Math.min(100, Math.max(0, reading + w.offset));
  const isPess = w.name === "pessimistic";
  const past = isPess ? kneeMayBePassed(c, reading) : soc >= w.knee;
  const anchor = inForceW === null ? rateW : isPess ? Math.min(inForceW, rateW) : inForceW;
  return { t, soc, kneeAt: past ? t - w.dropMin - 1 : null, kneeW: past ? anchor : null };
}

/** Integral of the fall factor over the time since the knee from a to b (minutes), 1 on the plateau side, `tr` after the fall of length `drop`. */
function fallIntegral(a: number, b: number, tr: number, drop: number): number {
  if (drop <= 0) return tr * (b - a);
  const a1 = Math.min(Math.max(a, 0), drop);
  const b1 = Math.min(Math.max(b, 0), drop);
  const ramp = (b1 - a1) - ((1 - tr) * (b1 * b1 - a1 * a1)) / (2 * drop);
  const rest = tr * (b - Math.max(a, drop));
  return ramp + Math.max(0, rest);
}

/**
 * Advances the state with a constant setpoint until `until` (real minutes since the window opened) or until the target is reached; returns the minute the
 * target is reached, or null. The plateau is linear; after the knee the factor falls to the tail, which is anchored to the plateau power at the knee.
 */
function advance(w: World, st: SimState, rateW: number, until: number, target: number): number | null {
  if (!(rateW > 0)) {
    // no charge at all (a guard: a rate in force is validated and a candidate is at least the minimum, so this never divides by zero)
    if (st.t < until) st.t = until;
    return null;
  }
  const perMin = (rateW * w.eff) / 1000 / 60 / w.pctKwh;
  while (st.t < until - EPS) {
    const dt = Math.min(1, until - st.t);
    if (st.kneeAt === null) {
      if (st.soc + perMin * dt >= w.knee - EPS && w.knee < 100) {
        const used = perMin > 0 ? Math.max(0, (w.knee - st.soc) / perMin) : 0;
        if (target <= w.knee + EPS && st.soc + perMin * used >= target - EPS) return finishPlateau(st, perMin, target);
        st.soc = w.knee;
        st.kneeAt = st.t + used;
        st.kneeW = rateW;
        const rest = dt - used;
        const tr = Math.min(1, (w.tail * (st.kneeW as number)) / rateW);
        const gain = perMin * fallIntegral(0, rest, tr, w.dropMin);
        if (st.soc + gain >= target - EPS) return finishLinear(st, used, rest, gain, target);
        st.soc += gain;
        st.t += dt;
        continue;
      }
      if (st.soc + perMin * dt >= target - EPS) return finishPlateau(st, perMin, target);
      st.soc += perMin * dt;
      st.t += dt;
      continue;
    }
    if (st.kneeW === null) st.kneeW = rateW;
    const tr = Math.min(1, (w.tail * st.kneeW) / rateW);
    const gain = perMin * fallIntegral(st.t - st.kneeAt, st.t + dt - st.kneeAt, tr, w.dropMin);
    if (st.soc + gain >= target - EPS) return finishLinear(st, 0, dt, gain, target);
    st.soc += gain;
    st.t += dt;
  }
  return null;
}

function finishPlateau(st: SimState, perMin: number, target: number): number {
  const at = st.t + (perMin > 0 ? Math.max(0, (target - st.soc) / perMin) : 0);
  st.t = at;
  st.soc = target;
  return at;
}

/** The target is crossed inside a step: the crossing is placed by linear interpolation of the step's gain (later than the truth on a falling curve: pessimistic). */
function finishLinear(st: SimState, offset: number, span1: number, gain: number, target: number): number {
  const at = st.t + offset + (gain > 0 ? (span1 * (target - st.soc)) / gain : span1);
  st.t = at;
  st.soc = target;
  return at;
}

interface Ctx {
  target: number;
  deadline: number;
  windowEnd: number;
  cands: number[];
  ceilingW: number;
  minW: number;
  stepW: number;
  dwell: number;
  maxChanges: number;
  midWindow: boolean;
  hysteresis: number;
  slack: number;
  tick: number;
  /** Points the reading's true position may be ABOVE the displayed reading (resolution / 2 + noise): the optimistic estimate decides the knee. */
  upOffset: number;
  /** True when the path cannot change a rate after the START (midWindowAdjustment false): a rate above the ceiling then gives a STOP, never a change. */
  fixedPath: boolean;
  pess: World;
  exp: World;
  opt: World;
}

/** The lowest candidate whose constant-rate PESSIMISTIC simulation reaches the target by `deadline`; when none does, the top candidate and `feasible` false. */
function lowestFeasible(c: Ctx, t: number, reading: number, inForceW: number | null, deadline: number): { rateW: number; feasible: boolean } {
  const reaches = (s: number): boolean => {
    const st = startState(c, c.pess, t, reading, inForceW, s);
    const f = advance(c.pess, st, s, deadline, c.target);
    return f !== null && f <= deadline + EPS;
  };
  let hi = c.cands.length - 1;
  if (!reaches(c.cands[hi] as number)) return { rateW: c.cands[hi] as number, feasible: false };
  let lo = 0;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (reaches(c.cands[mid] as number)) hi = mid;
    else lo = mid + 1;
  }
  return { rateW: c.cands[lo] as number, feasible: true };
}

interface Choice {
  rateW: number;
  change: NightChange;
  codes: NightCode[];
  neededW: number;
  neededMeetsDeadline: boolean;
}

/** The one decision at one time: the same function decides NOW and every re-plan the projection makes, so the trajectory is the policy itself. */
function choose(c: Ctx, reading: number, simT: number, now: number, f: NightInForce): Choice {
  const codes: NightCode[] = [];
  const cur = f.setpointW === null ? null : Math.min(f.setpointW, c.ceilingW);
  const need = lowestFeasible(c, simT, reading, cur, c.deadline);
  if (f.setpointW === null || cur === null) {
    codes.push("START");
    codes.push(!need.feasible ? "RATE_AT_CEILING" : need.rateW <= c.minW ? "RATE_AT_MINIMUM" : "RATE_GENTLEST");
    return { rateW: need.rateW, change: "START", codes, neededW: need.rateW, neededMeetsDeadline: need.feasible };
  }
  if (f.setpointW > c.ceilingW) {
    codes.push("FORCED_BELOW_CEILING");
    if (c.fixedPath) {
      // The path fixes the rate at the START: it cannot come down to the ceiling, so the only safe recommendation is a stop (never a change).
      codes.push("ACTUATOR_FIXED_RATE");
      return { rateW: f.setpointW, change: "STOP", codes, neededW: need.rateW, neededMeetsDeadline: need.feasible };
    }
  }
  const held = cur;
  const dwellOk = f.lastChangeAtMin === null || now - f.lastChangeAtMin >= c.dwell - EPS;
  const budgetOk = f.changesUsed < c.maxChanges;
  const pathOk = c.midWindow && c.maxChanges > 0;
  const pastKnee = kneeMayBePassed(c, reading);
  const canChange = pathOk && budgetOk && dwellOk && !pastKnee;
  const heldCode: NightCode = !pathOk ? "HELD_PATH_FIXED" : !budgetOk ? "HELD_BUDGET" : !dwellOk ? "HELD_DWELL" : "HELD_PAST_KNEE";
  const st = startState(c, c.pess, simT, reading, held, held);
  const fin = advance(c.pess, st, held, c.deadline, c.target);
  const curOk = fin !== null && fin <= c.deadline + EPS;
  let rate = held;
  if (!curOk) {
    if (need.rateW > held) {
      if (canChange) {
        rate = need.rateW;
        codes.push("INCREASE_NEEDED");
      } else codes.push(heldCode);
    }
    if (!need.feasible) codes.push("RATE_AT_CEILING");
  } else {
    const low = lowestFeasible(c, simT, reading, held, c.deadline - c.slack);
    const lowRate = low.feasible ? low.rateW : held;
    if (held - lowRate >= c.hysteresis - EPS && lowRate >= c.minW) {
      if (canChange) {
        rate = lowRate;
        codes.push("DECREASE_SAVES");
      } else codes.push(heldCode);
    }
  }
  const change: NightChange = rate > f.setpointW ? "INCREASE" : rate < f.setpointW ? "DECREASE" : "KEEP";
  return { rateW: rate, change, codes, neededW: need.rateW, neededMeetsDeadline: need.feasible };
}

interface Projection {
  segments: TrajectoryPoint[];
  outcome: WorldOutcome;
}

/**
 * Runs the policy in one world: the first decision (the same for every world), then, when `replan`, a re-plan at each tick from the world's own SOC,
 * inside the change budget and dwell; without `replan` the first rate is HELD for the rest of the window (the status basis). After a STOP the rate in
 * force is what is held (what happens if nothing is done).
 */
function project(c: Ctx, w: World, reading0: number, now: number, first: Choice, force0: NightInForce, replan: boolean): Projection {
  const t0 = Math.max(now, 0);
  const forcedOnly = first.codes.includes("FORCED_BELOW_CEILING") && first.rateW === c.ceilingW;
  const drawsBudget = (first.change === "INCREASE" || first.change === "DECREASE") && !forcedOnly;
  let f: NightInForce = { setpointW: first.rateW, lastChangeAtMin: first.change === "KEEP" ? force0.lastChangeAtMin : t0, changesUsed: force0.changesUsed + (drawsBudget ? 1 : 0) };
  const segments: TrajectoryPoint[] = [{ atMin: t0, inMin: t0 - now, setpointW: first.rateW, change: first.change, conditional: false }];
  const inForceW = force0.setpointW === null ? null : first.change === "STOP" ? force0.setpointW : Math.min(force0.setpointW, c.ceilingW);
  const st = startState(c, w, t0, reading0, inForceW, first.rateW);
  let finish: number | null = null;
  if (replan && c.midWindow && c.maxChanges > 0) {
    for (let k = 1; ; k++) {
      const tk = t0 + k * c.tick;
      if (tk >= c.deadline - EPS || tk >= c.windowEnd) break;
      finish = advance(w, st, f.setpointW as number, tk, c.target);
      if (finish !== null) break;
      if (f.changesUsed >= c.maxChanges) break;
      const ch = choose(c, st.soc - w.offset, tk, tk, f);
      if (ch.rateW !== f.setpointW) {
        segments.push({ atMin: tk, inMin: tk - now, setpointW: ch.rateW, change: ch.change, conditional: true });
        f = { setpointW: ch.rateW, lastChangeAtMin: tk, changesUsed: f.changesUsed + 1 };
      }
    }
  }
  let socAtDeadline = c.target;
  if (finish === null) {
    finish = advance(w, st, f.setpointW as number, Math.max(c.deadline, st.t), c.target);
    if (finish === null) {
      socAtDeadline = st.soc;
      finish = advance(w, st, f.setpointW as number, Math.max(c.windowEnd, st.t), c.target);
    }
  }
  return { segments, outcome: { finishMin: finish, socAtDeadlinePct: Math.round(Math.min(100, socAtDeadline) * 10) / 10, reachedByDeadline: finish !== null && finish <= c.deadline + EPS } };
}

// ---- the planner -------------------------------------------------------------------------------------------------------------------------------

function refuse(status: NightStatus, codes: NightCode[], bits: Partial<GentleNightPlan> = {}, extra = ""): GentleNightPlan {
  const reasons = codes.map((k) => CODE_TEXT[k]);
  if (extra !== "") reasons.push(extra);
  return {
    label: CONTROLLER_LABEL, status, codes, reasons, targetSocPct: null, bufferMin: null, windowRealMin: null, deadlineMin: null, deadlineInMin: null,
    now: { setpointW: null, change: "NONE", neededW: null, neededMeetsDeadline: null, ceilingW: null, ceilingName: null, minW: LIMITS.chargePowerMin, stepW: 100 },
    trajectory: [], expectedFinish: null, band: null, marginMin: null, bufferThatWouldFitMin: null, stopRecommended: false, profile: null,
    needed: ["Nothing can be recommended from these inputs, so nothing is to be applied: the fallback holds whatever is in force."], unknowns: UNKNOWNS.slice(), assumptions: null,
    actuationSupported: false, actuationReason: ACTUATION_REASON, guarantee: "NONE", guaranteeNote: NIGHT_GUARANTEE_NOTE, ...bits,
  };
}

const UNKNOWNS: readonly string[] = Object.freeze([
  "the setpoint unit (AC grid watts, DC battery watts or amps at a voltage)",
  "the BMS response at rates below the top rate (no data)",
  "the SOC at which the charge power falls (no SOC series was saved): the knee is an assumption",
  "the live BMS charge limit and any derating (not read)",
]);

function paramsProblem(p: GentleNightParams): string | null {
  for (const k of Object.keys(BOUNDS) as (keyof GentleNightParams)[]) {
    const v = p[k];
    const b = BOUNDS[k];
    if (!isNum(v) || v < b[0] || v > b[1]) return "Parameter " + k + " is not a number from " + b[0] + " to " + b[1] + ".";
  }
  if (!(p.chargeEffMin <= p.chargeEff && p.chargeEff <= p.chargeEffMax)) return "The efficiency band must satisfy min <= expected <= max.";
  if (!(p.tailFraction <= p.tailFractionExpected && p.tailFractionExpected <= p.tailFractionOptimistic)) return "The tail fractions must satisfy pessimistic <= expected <= optimistic.";
  if (p.minW % p.stepW !== 0 && ceilStep(p.minW, p.stepW) > p.hardMaxW) return "The step does not fit between the minimum and the maximum.";
  return null;
}

/**
 * The night plan. See the file header. Never throws on bad input: it returns INPUTS_UNUSABLE with codes. The input is never changed.
 */
export function planGentleNight(input: GentleNightInput): GentleNightPlan {
  if (input === null || typeof input !== "object") return refuse("INPUTS_UNUSABLE", ["INPUT_INVALID"]);
  // parameters: only a number inside its bounds is taken; anything else is invalid, never silently defaulted
  const given = input.params !== undefined && input.params !== null && typeof input.params === "object" ? input.params : {};
  const merged: GentleNightParams = { ...DEFAULT_NIGHT_PARAMS };
  for (const k of Object.keys(DEFAULT_NIGHT_PARAMS) as (keyof GentleNightParams)[]) if ((given as Record<string, unknown>)[k] !== undefined) merged[k] = (given as Record<string, number>)[k] as number;
  const bad = paramsProblem(merged);
  if (bad !== null) return refuse("INPUTS_UNUSABLE", ["PARAMS_INVALID"], {}, bad);
  const profileNamed = input.actuatorProfile !== undefined;
  const profileId: ActuatorProfileId = profileNamed ? (input.actuatorProfile as ActuatorProfileId) : "FREE_POWER_LEASE";
  if (!Object.prototype.hasOwnProperty.call(GENTLE_ACTUATOR_PROFILES, profileId)) return refuse("INPUTS_UNUSABLE", ["PROFILE_INVALID"]);
  const tightened = applyActuatorProfile({ ...DEFAULT_GENTLE_PARAMS, stepW: merged.stepW, minW: merged.minW, hardMaxW: merged.hardMaxW, dwellMin: merged.dwellMin, maxChanges: merged.maxChanges }, profileId).params;
  const profile = GENTLE_ACTUATOR_PROFILES[profileId];
  const P: GentleNightParams = { ...merged, stepW: tightened.stepW, minW: tightened.minW, hardMaxW: Math.min(tightened.hardMaxW, LIMITS.chargePowerMax), dwellMin: tightened.dwellMin, maxChanges: tightened.maxChanges };

  const target = input.targetSocPct;
  if (!isNum(target) || target < 10 || target > 100) return refuse("INPUTS_UNUSABLE", ["TARGET_INVALID"]);
  const buffer = input.bufferMin === undefined ? 60 : input.bufferMin;
  if (!isNum(buffer) || buffer < 0 || buffer > 120 || buffer % 5 !== 0) return refuse("INPUTS_UNUSABLE", ["BUFFER_INVALID"]);
  const win = input.chargeWindow;
  if (win === null || typeof win !== "object" || !Number.isInteger(win.startMin) || !Number.isInteger(win.endMin) || win.startMin < 0 || win.startMin > 1439 || win.endMin < 0 || win.endMin > 1439 || win.startMin === win.endMin) {
    return refuse("INPUTS_UNUSABLE", ["WINDOW_INVALID"]);
  }
  const day = input.clockDay;
  if (day === null || typeof day !== "object" || !isNum(day.changeAtMin) || (day.deltaMin !== 0 && day.deltaMin !== 60 && day.deltaMin !== -60)) return refuse("INPUTS_UNUSABLE", ["CLOCK_DAY_INVALID"]);
  if (windowTouchesClockChange(win.startMin, win.endMin, day)) return refuse("CLOCK_CHANGE_NIGHT_REFUSED", ["CLOCK_CHANGE_NIGHT"]);
  const W = windowRealMinutes(win.startMin, win.endMin, day);
  if (W === null) return refuse("INPUTS_UNUSABLE", ["WINDOW_INVALID"]);
  const elapsed = input.elapsedMin;
  if (!isNum(elapsed) || elapsed < -720) return refuse("INPUTS_UNUSABLE", ["ELAPSED_INVALID"]);

  const codes: NightCode[] = [];
  if (!profileNamed) codes.push("PROFILE_DEFAULT_MOST_RESTRICTIVE");
  // SOC: unknown, stale or implausible is never guessed
  const soc = input.socPct;
  if (soc === null || soc === undefined || !isNum(soc)) return refuse("INPUTS_UNUSABLE", ["NO_SOC"]);
  const age = input.socAgeMin;
  if (!isNum(age) || age < 0 || age > P.maxSocAgeMin) return refuse("INPUTS_UNUSABLE", ["STALE_SOC"]);
  if (soc < 0 || soc > 100) return refuse("INPUTS_UNUSABLE", ["SOC_IMPLAUSIBLE"]);
  const prev = input.previousSoc;
  if (prev !== undefined && prev !== null) {
    if (typeof prev !== "object" || !isNum(prev.socPct) || !isNum(prev.elapsedMin) || prev.elapsedMin > elapsed) return refuse("INPUTS_UNUSABLE", ["SOC_IMPLAUSIBLE"]);
    const hours = (elapsed - prev.elapsedMin) / 60;
    if (soc < prev.socPct - P.socRegressionTolPct || soc > prev.socPct + P.socResolutionPct + P.socRegressionTolPct + P.socJumpPctPerHour * hours) return refuse("INPUTS_UNUSABLE", ["SOC_IMPLAUSIBLE"]);
  }
  // capacity: the larger of the trusted figure and a learned one; never guessed
  const learned = input.learnedCapacityKwh;
  const nominal = input.capacityKwh;
  if (!isNum(nominal) || nominal <= 0 || nominal > 500) return refuse("INPUTS_UNUSABLE", ["CAPACITY_UNUSABLE"]);
  const capKwh = isNum(learned) && learned > 0 && learned <= 500 ? Math.max(nominal, learned) : nominal;
  // the force record (what is in force now); 0 W is "not charging": the recommendation is then a START
  const given0 = input.inForce === undefined || input.inForce === null ? { setpointW: null, lastChangeAtMin: null, changesUsed: 0 } : input.inForce;
  if (typeof given0 !== "object" || (given0.setpointW !== null && (!isNum(given0.setpointW) || given0.setpointW < 0)) || !Number.isInteger(given0.changesUsed) || given0.changesUsed < 0 || (given0.lastChangeAtMin !== null && !isNum(given0.lastChangeAtMin))) {
    return refuse("INPUTS_UNUSABLE", ["INPUT_INVALID"]);
  }
  const force: NightInForce = given0.setpointW === 0 ? { setpointW: null, lastChangeAtMin: given0.lastChangeAtMin, changesUsed: given0.changesUsed } : given0;
  if (given0.setpointW === 0) codes.push("IN_FORCE_ZERO_NOT_CHARGING");
  const deadline = W - buffer;
  // before the window: the SOC at the window start is the reading less a given pessimistic drain bound, in the most points per kWh the bands allow
  let socPlan = soc;
  if (elapsed < 0) {
    const drain = input.preWindowDrainW;
    if (!isNum(drain) || drain < 0 || drain > 30000) return refuse("INPUTS_UNUSABLE", ["PRE_WINDOW_DRAIN_UNKNOWN"]);
    const fewestKwhPerPct = (capKwh * (1 - P.capacityBandPct / 100)) / (1 + P.socScaleErrPct / 100) / 100;
    socPlan = Math.max(0, soc - (drain * (age - elapsed)) / 60 / 1000 / fewestKwhPerPct);
  }

  if (socPlan >= target) {
    const c0: NightCode[] = ["AT_TARGET"];
    if (target >= 100) c0.push("TOP_OF_CHARGE_TAIL");
    return refuse("NO_NEED", c0, { targetSocPct: target, bufferMin: buffer, windowRealMin: W, deadlineMin: deadline, deadlineInMin: deadline - elapsed });
  }
  if (elapsed >= W) return refuse("INPUTS_UNUSABLE", ["WINDOW_OVER"], { targetSocPct: target, bufferMin: buffer, windowRealMin: W, deadlineMin: deadline, deadlineInMin: deadline - elapsed });

  // limits: the smallest known fresh ceiling (never guessed), the firmware bound, and the grid headroom only when a limit AND a fresh demand are known
  if (!Array.isArray(input.ceilings)) return refuse("INPUTS_UNUSABLE", ["NO_SAFE_CEILING"]);
  if (input.ceilings.some((x) => x !== null && typeof x === "object" && isNum(x.watts) && x.watts >= 0 && (x.ageMin === undefined || x.ageMin === null))) codes.push("CEILING_AGE_UNKNOWN");
  const eff = effectiveCeiling(input.ceilings, P.maxCeilingAgeMin, (x) => ceilingInSetpointUnits(x, "UNSETTLED", P.setpointConversionEff, P.setpointOvershoot));
  if (eff.best === null) return refuse("INPUTS_UNUSABLE", ["NO_SAFE_CEILING"]);
  let ceiling = Math.min(eff.best.watts, P.hardMaxW);
  let ceilingName = eff.best.watts <= P.hardMaxW ? eff.best.name : "firmware_setpoint_bound";
  const hh = input.household !== undefined && input.household !== null && typeof input.household === "object" ? input.household : {};
  const gridLimit = hh.gridImportLimitW;
  if (gridLimit === undefined || gridLimit === null) codes.push("GRID_LIMIT_UNKNOWN_NO_CAP");
  else {
    if (!isNum(gridLimit) || gridLimit < 0) return refuse("INPUTS_UNUSABLE", ["INPUT_INVALID"]);
    const lage = hh.gridImportLimitAgeMin;
    if (lage !== undefined && lage !== null && (!isNum(lage) || lage < 0 || lage > P.maxGridLimitAgeMin)) return refuse("INPUTS_UNUSABLE", ["GRID_LIMIT_STALE"]);
    const peak = hh.demandPeakW;
    const dage = hh.demandAgeMin;
    if (!isNum(peak) || peak < 0 || !isNum(dage) || dage < 0 || dage > P.maxHouseholdAgeMin) return refuse("INPUTS_UNUSABLE", ["DEMAND_UNKNOWN"]);
    const cap = Math.max(0, ((gridLimit - peak * (1 + P.demandMarginPct / 100)) * P.setpointConversionEff) / P.setpointOvershoot);
    if (cap < ceiling) {
      ceiling = cap;
      ceilingName = "grid_headroom";
    }
  }
  ceiling = floorStep(ceiling, P.stepW);
  const minW = ceilStep(P.minW, P.stepW);
  if (ceiling < minW) return refuse("INPUTS_UNUSABLE", [ceilingName === "grid_headroom" ? "HEADROOM_BELOW_MIN" : "CEILING_BELOW_MIN"]);
  // a rate in force above the ceiling is always forced down (or stopped); one at or below it must be a setpoint the path can hold
  const inW = force.setpointW;
  if (inW !== null && inW <= ceiling + EPS && (inW < minW - EPS || Math.abs(inW / P.stepW - Math.round(inW / P.stepW)) > 1e-9)) return refuse("INPUTS_UNUSABLE", ["IN_FORCE_INVALID"]);
  const cands: number[] = [];
  for (let s = minW; s <= ceiling + EPS; s += P.stepW) cands.push(s);

  // the three worlds
  const band = P.capacityBandPct / 100;
  const scale = P.socScaleErrPct / 100;
  const kneeP = P.kneeSocPct;
  const world = (name: World["name"], pctKwh: number, e: number, knee: number, tail: number, drop: number, offset: number): World => ({ name, pctKwh, eff: e, knee, tail, dropMin: drop, offset });
  const pess = world("pessimistic", (capKwh * (1 + band)) / (1 - scale) / 100, P.chargeEffMin, kneeP, P.tailFraction, Math.min(1, P.dropMin), -(P.socResolutionPct / 2 + P.socNoisePct));
  const kneeAbove = (add: number): number => (kneeP >= 99.5 ? kneeP : Math.min(99.5, kneeP + add));
  const expW = world("expected", capKwh / 100, P.chargeEff, kneeAbove(P.kneeSpreadPct), P.tailFractionExpected, P.dropMin, 0);
  const optW = world("optimistic", (capKwh * (1 - band)) / (1 + scale) / 100, P.chargeEffMax, kneeAbove(2 * P.kneeSpreadPct), P.tailFractionOptimistic, P.dropMin, P.socResolutionPct / 2);
  const midWindow = profile.midWindowAdjustment && P.maxChanges > 0;
  const ctx: Ctx = {
    target, deadline, windowEnd: W, cands, ceilingW: ceiling, minW, stepW: P.stepW, dwell: P.dwellMin, maxChanges: P.maxChanges, midWindow, hysteresis: P.hysteresisW,
    slack: P.decreaseSlackMin, tick: Math.max(P.replanMin, P.dwellMin), upOffset: P.socResolutionPct / 2 + P.socNoisePct, fixedPath: !profile.midWindowAdjustment,
    pess, exp: expW, opt: optW,
  };

  if (elapsed < 0) codes.push("BEFORE_WINDOW");
  if (elapsed > deadline) codes.push("DEADLINE_PASSED_WINDOW_OPEN");
  const first = choose(ctx, socPlan, Math.max(elapsed, 0), elapsed, force);
  for (const k of first.codes) if (!codes.includes(k)) codes.push(k);
  const pp = project(ctx, pess, socPlan, elapsed, first, force, true);
  const ph = project(ctx, pess, socPlan, elapsed, first, force, false);
  const pe = project(ctx, expW, socPlan, elapsed, first, force, true);
  const po = project(ctx, optW, socPlan, elapsed, first, force, true);
  // The status basis is the pessimistic world with the first rate HELD: no path makes a later change by itself (see the header), so OK never relies on one.
  const pf = ph.outcome.finishMin;
  const ef = pe.outcome.finishMin;
  const basisOk = pf !== null && pf <= deadline + EPS;
  const plannedOk = pp.outcome.finishMin !== null && pp.outcome.finishMin <= deadline + EPS;
  const stop = first.change === "STOP";
  let status: NightStatus;
  if (stop) status = "STOP_RECOMMENDED";
  else if (basisOk) status = "OK";
  else if (plannedOk || (ef !== null && ef <= deadline + EPS) || (pf !== null && pf <= W + EPS)) status = "TARGET_AT_RISK";
  else status = "UNREACHABLE";
  if (plannedOk && !basisOk) codes.push("RELIES_ON_LATER_CHANGE");
  if (!basisOk) codes.push("PESSIMISTIC_MISSES_DEADLINE");
  if (status === "TARGET_AT_RISK" && ef !== null && ef <= deadline + EPS && !(pf !== null && pf <= W + EPS)) codes.push("RATE_NOT_ENOUGH_ALONE");
  if (target > kneeP) codes.push("TARGET_ABOVE_KNEE");
  if (target >= 100) codes.push("TOP_OF_CHARGE_TAIL");
  codes.push("SETPOINT_UNIT_UNSETTLED");
  const uniq = codes.filter((k, i) => codes.indexOf(k) === i);

  const startMin = win.startMin;
  const exFinish = ef === null ? null : { atMin: Math.round(ef * 10) / 10, inMin: Math.round((ef - elapsed) * 10) / 10, wallClock: fmt(startMin + Math.round(ef)) };
  const usedAfter = force.changesUsed + ((first.change === "INCREASE" || first.change === "DECREASE") && !(first.codes.includes("FORCED_BELOW_CEILING") && first.rateW === ceiling) ? 1 : 0);
  const changesLeft = Math.max(0, P.maxChanges - usedAfter);
  const adaptive = midWindow && (profileId === "RATE_CONTROLLER_PROPOSED" || profileId === "UNCONSTRAINED");
  const reportProfile: NightProfileReport = {
    id: profileId, label: profile.label, existsToday: profile.existsToday, maxChanges: P.maxChanges, changesLeft, dwellMin: P.dwellMin, midWindowAdjustment: midWindow,
    ownerConfirmationPerChange: profile.ownerConfirmationPerChange, adaptive,
    adaptiveNote: profileId === "FREE_POWER_LEASE"
      ? "No adaptation: the rate is fixed at the START and cannot change afterwards, so the trajectory is one flat rate."
      : profileId === "TOU_SLOT_EDITOR"
        ? "At most one coarse change, each one needs the owner's typed confirmation: the trajectory is flat, with at most one conditional change."
        : profileId === "RATE_CONTROLLER_PROPOSED"
          ? "Adaptive only on a rate controller that does not exist yet (up to " + P.maxChanges + " changes, " + P.dwellMin + " min apart); every later point is conditional."
          : "No path assumed: the generic closed-loop policy with the default budget; not a statement about any real path.",
  };
  const rate = first.rateW;
  const needed: string[] = [
    "Nothing here applies the rate: a person or a future controller has to.",
    stop
      ? "Stop the charge on this path: the rate in force (" + rate + " W) is above the safe ceiling (" + ceiling + " W) and the path cannot lower it; a new START at or below " + ceiling + " W would be a new decision."
      : profileId === "TOU_SLOT_EDITOR"
      ? "The owner's guarded TOU editor: Review, the typed phrase with its one-time code, Apply, with the charge slot power set to " + rate + " W before the window; each further change needs a new confirmation after " + P.dwellMin + " min; the editor refuses clock-change nights and near slot boundaries."
      : profileId === "FREE_POWER_LEASE"
        ? "The Free Power start (the scheduled Charge Battery package or the button) with the staged power " + rate + " W: it is fixed for the lease."
        : profileId === "RATE_CONTROLLER_PROPOSED"
          ? "A guarded rate controller that does not exist: the proofs in GENTLE_LIVE_ACTUATION_PROOF.md must exist first, each with the owner's own authorisation."
          : "Pick one actuator path first: the generic model assumes none.",
    "The setpoint unit is not established: treat the figure as a plan, not as a measured power.",
  ];
  if (uniq.includes("GRID_LIMIT_UNKNOWN_NO_CAP")) needed.push("The safe grid import limit is unknown: nothing caps the rate against it.");
  const reasons = uniq.map((k) => CODE_TEXT[k]);
  return {
    label: CONTROLLER_LABEL, status, codes: uniq, reasons, targetSocPct: target, bufferMin: buffer, windowRealMin: W, deadlineMin: deadline, deadlineInMin: deadline - elapsed,
    now: { setpointW: stop ? null : rate, change: first.change, neededW: first.neededW, neededMeetsDeadline: first.neededMeetsDeadline, ceilingW: ceiling, ceilingName, minW, stepW: P.stepW },
    trajectory: stop ? [] : pe.segments.map((s) => ({ ...s, atMin: Math.round(s.atMin * 10) / 10, inMin: Math.round(s.inMin * 10) / 10, conditional: s.conditional })),
    expectedFinish: exFinish,
    band: { pessimistic: pp.outcome, expected: pe.outcome, optimistic: po.outcome, pessimisticHeld: ph.outcome },
    marginMin: pf === null ? null : Math.round((deadline - pf) * 10) / 10,
    bufferThatWouldFitMin: pf !== null && W - pf >= 0 ? Math.min(120, Math.floor((W - pf) / 5 + EPS) * 5) : null,
    stopRecommended: stop,
    profile: reportProfile, needed, unknowns: UNKNOWNS.slice(),
    assumptions: {
      capacityKwh: capKwh, capacityBandPct: P.capacityBandPct, chargeEff: P.chargeEff, chargeEffMin: P.chargeEffMin, chargeEffMax: P.chargeEffMax, socScaleErrPct: P.socScaleErrPct,
      kneePessimisticPct: pess.knee, kneeExpectedPct: expW.knee, kneeOptimisticPct: optW.knee, tailPessimistic: pess.tail, tailExpected: expW.tail, tailOptimistic: optW.tail,
      setpointOvershoot: P.setpointOvershoot, startOffsetPessimisticPct: pess.offset, socAtPlanStartPct: Math.round(socPlan * 100) / 100,
    },
    actuationSupported: false, actuationReason: ACTUATION_REASON, guarantee: "NONE", guaranteeNote: NIGHT_GUARANTEE_NOTE,
  };
}
