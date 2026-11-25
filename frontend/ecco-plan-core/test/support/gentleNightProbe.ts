// The behaviour probe and the single-line mutants of the Gentle night planner (src/gentleNight.ts), shared by test/gentleNightMutants.test.ts (each
// mutant must differ from the COMMITTED golden probe, test/gentleNightProbe.golden.json) and by tools/night_mutation_score.py (each mutant run against the
// assertion suites, which import nothing from here). The probe summarises how a module behaves in many named scenarios; it is a function of the module.
import type * as Night from "../../src/gentleNight.ts";
import type { GentleNightInput, GentleNightPlan } from "../../src/gentleNight.ts";
import { maxChargePowerCeiling } from "../../src/gentleController.ts";
import { slot } from "../fixtures.ts";

export type Mod = Pick<typeof Night, "planGentleNight" | "windowFromSlotTable" | "windowTouchesClockChange">;
const ORD = { changeAtMin: 0, deltaMin: 0 } as const;
/** No path named here on purpose: the generic model is named explicitly below, and the default path has its own key. */
const bare: GentleNightInput = {
  targetSocPct: 80, chargeWindow: { startMin: 30, endMin: 330 }, clockDay: ORD, elapsedMin: 0, socPct: 20, socAgeMin: 1, capacityKwh: 31.7, ceilings: [maxChargePowerCeiling(8000, 8000)],
};
const base: GentleNightInput = { ...bare, actuatorProfile: "UNCONSTRAINED" };

const round = (x: number | null): number | null => (x === null ? null : Math.round(x * 100) / 100);
function sum(p: GentleNightPlan): unknown {
  const worlds = p.band === null ? null : [p.band.pessimistic, p.band.expected, p.band.optimistic, p.band.pessimisticHeld];
  return {
    status: p.status, codes: p.codes, now: p.now, traj: p.trajectory.map((t) => [t.atMin, t.setpointW, t.change, t.conditional]), margin: p.marginMin, fit: p.bufferThatWouldFitMin,
    band: worlds === null ? null : worlds.map((w) => [round(w.finishMin), w.socAtDeadlinePct, w.reachedByDeadline]), stop: p.stopRecommended,
    finish: p.expectedFinish, deadline: [p.windowRealMin, p.deadlineMin, p.deadlineInMin], profile: p.profile,
  };
}

/** One summary per behaviour; a thrown error counts as a different summary ("THROW"), which also kills a mutant that breaks the module. */
export function signature(m: Mod): Record<string, string> {
  const plan = (over: Partial<GentleNightInput> = {}): GentleNightPlan => m.planGentleNight({ ...base, ...over });
  const out: Record<string, string> = {};
  const rec = (key: string, f: () => unknown): void => {
    try {
      out[key] = JSON.stringify(f());
    } catch {
      out[key] = "THROW";
    }
  };
  const night = (over: Partial<GentleNightInput>): unknown => sum(plan(over));
  const small = (over: Partial<GentleNightInput>): unknown => {
    const p = plan(over);
    return [p.status, p.codes, p.now.setpointW, p.now.ceilingW, p.now.ceilingName, p.now.change];
  };
  const f2000 = { setpointW: 2000, lastChangeAtMin: -60, changesUsed: 0 };
  rec("A", () => night({}));
  rec("A60", () => night({ targetSocPct: 60 }));
  rec("B", () => night({ targetSocPct: 93, socPct: 40 }));
  rec("C", () => night({ targetSocPct: 95, socPct: 85, inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } }));
  rec("C93", () => night({ targetSocPct: 93, socPct: 85, inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } }));
  rec("D", () => night({ targetSocPct: 95, socPct: 93, elapsedMin: 60, inForce: { setpointW: 5200, lastChangeAtMin: 0, changesUsed: 0 } }));
  rec("E", () => night({ targetSocPct: 100, socPct: 10, bufferMin: 120, ceilings: [maxChargePowerCeiling(8000, 3000)] }));
  rec("F", () => night({ targetSocPct: 95, socPct: 40 }));
  rec("RC", () => night({ actuatorProfile: "RATE_CONTROLLER_PROPOSED" }));
  rec("TOU", () => night({ actuatorProfile: "TOU_SLOT_EDITOR" }));
  rec("FREE", () => night({ actuatorProfile: "FREE_POWER_LEASE" }));
  rec("defaultProfile", () => [sum(m.planGentleNight({ ...bare })), sum(m.planGentleNight({ ...bare, inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 }, targetSocPct: 60 }))]);
  rec("deadlineDefault", () => small({ bufferMin: undefined }));
  rec("bufferStep", () => [small({ bufferMin: 7 }), small({ bufferMin: 35 })]);
  rec("bufferMax", () => [small({ bufferMin: 125 }), small({ bufferMin: 120 }), small({ bufferMin: -5 })]);
  rec("targetBounds", () => [small({ targetSocPct: 5 }), small({ targetSocPct: 100.5 }), small({ targetSocPct: 10 }), small({ targetSocPct: 100 })]);
  rec("clockSpring", () => [m.windowTouchesClockChange(30, 330, { changeAtMin: 120, deltaMin: 60 }), m.windowTouchesClockChange(150, 160, { changeAtMin: 120, deltaMin: 60 }), m.windowTouchesClockChange(23 * 60, 2 * 60 + 30, { changeAtMin: 120, deltaMin: 60 }),
    m.windowTouchesClockChange(3 * 60 + 30, 6 * 60, { changeAtMin: 120, deltaMin: 60 }), m.windowTouchesClockChange(10 * 60, 12 * 60, { changeAtMin: 120, deltaMin: 60 })]);
  rec("clockAutumn", () => [m.windowTouchesClockChange(3 * 60 + 30, 6 * 60, { changeAtMin: 180, deltaMin: -60 }), m.windowTouchesClockChange(4 * 60, 6 * 60, { changeAtMin: 180, deltaMin: -60 }), m.windowTouchesClockChange(4 * 60 + 5, 6 * 60, { changeAtMin: 180, deltaMin: -60 }),
    m.windowTouchesClockChange(22 * 60, 1 * 60 + 30, { changeAtMin: 180, deltaMin: -60 }), m.windowTouchesClockChange(22 * 60, 2 * 60 + 30, { changeAtMin: 180, deltaMin: -60 })]);
  rec("clockPlan", () => [small({ clockDay: { changeAtMin: 120, deltaMin: 60 } }), small({ clockDay: { changeAtMin: 120, deltaMin: 60 }, chargeWindow: { startMin: 10 * 60, endMin: 15 * 60 } })]);
  rec("ordinaryDay", () => [small({}), m.windowTouchesClockChange(30, 330, ORD)]);
  rec("ceilingMin", () => [small({ ceilings: [maxChargePowerCeiling(8000, 5000)] }), small({ ceilings: [maxChargePowerCeiling(8000, 65500)] })]);
  rec("ceilingStep", () => small({ ceilings: [maxChargePowerCeiling(8000, 5050)] }));
  rec("minRate", () => [small({ socPct: 79 }), small({ socPct: 79.5, targetSocPct: 80 })]);
  rec("ceilingBelowMin", () => [small({ ceilings: [maxChargePowerCeiling(8000, 300)] }), small({ ceilings: [maxChargePowerCeiling(8000, 500)] })]);
  rec("noCeiling", () => [small({ ceilings: [] }), small({ ceilings: [{ name: "x", watts: null }] })]);
  rec("staleCeiling", () => [small({ ceilings: [{ name: "x", watts: 8000, ageMin: 90 }] }), small({ ceilings: [maxChargePowerCeiling(8000, 8000), { name: "x", watts: 3000, ageMin: 90 }] })]);
  rec("gridCap", () => [small({ household: { gridImportLimitW: 8000, demandPeakW: 2000, demandAgeMin: 1, gridImportLimitAgeMin: 5 } }), small({ household: { gridImportLimitW: 12000, demandPeakW: 0, demandAgeMin: 0 } }),
    small({ household: { gridImportLimitW: 3000, demandPeakW: 2500, demandAgeMin: 1 } })]);
  rec("gridJustBelow", () => [small({ household: { gridImportLimitW: 11000, demandPeakW: 1000, demandAgeMin: 1 }, targetSocPct: 100 })]);
  rec("gridAc", () => [small({ ceilings: [maxChargePowerCeiling(8000, 8000), { name: "grid_charge_limit", watts: 6000, basis: "GRID_AC" }] })]);
  rec("demandUnknown", () => [small({ household: { gridImportLimitW: 8000 } }), small({ household: { gridImportLimitW: 8000, demandPeakW: null, demandAgeMin: 1 } }), small({ household: { gridImportLimitW: 8000, demandPeakW: -5, demandAgeMin: 1 } })]);
  rec("demandStale", () => [small({ household: { gridImportLimitW: 8000, demandPeakW: 1000, demandAgeMin: 16 } }), small({ household: { gridImportLimitW: 8000, demandPeakW: 1000, demandAgeMin: 15 } }), small({ household: { gridImportLimitW: 8000, demandPeakW: 1000, demandAgeMin: null } })]);
  rec("gridStale", () => [small({ household: { gridImportLimitW: 8000, gridImportLimitAgeMin: 61, demandPeakW: 1000, demandAgeMin: 1 } }), small({ household: { gridImportLimitW: 8000, gridImportLimitAgeMin: 60, demandPeakW: 1000, demandAgeMin: 1 } })]);
  rec("gridUnknownSaid", () => [small({}), small({ household: {} })]);
  rec("staleSoc", () => [small({ socAgeMin: 16 }), small({ socAgeMin: 15 }), small({ socAgeMin: null }), small({ socAgeMin: -1 })]);
  rec("noSoc", () => [small({ socPct: null }), small({ socPct: undefined as unknown as number }), small({ socPct: NaN })]);
  rec("socRegression", () => [small({ socPct: 20, previousSoc: { socPct: 30, elapsedMin: -10 } }), small({ socPct: 28, previousSoc: { socPct: 30, elapsedMin: -10 } })]);
  rec("socJump", () => [small({ socPct: 40, elapsedMin: 6, previousSoc: { socPct: 20, elapsedMin: 0 } }), small({ socPct: 29, elapsedMin: 6, previousSoc: { socPct: 20, elapsedMin: 0 } }), small({ previousSoc: { socPct: 20, elapsedMin: 5 } })]);
  rec("prevFuture", () => [small({ previousSoc: { socPct: 20, elapsedMin: 1 } }), small({ previousSoc: { socPct: 20, elapsedMin: 0 } })]);
  rec("socRange", () => [small({ socPct: 101 }), small({ socPct: -1 }), small({ socPct: 100, targetSocPct: 100 })]);
  rec("capacityUnusable", () => [small({ capacityKwh: 0 }), small({ capacityKwh: null }), small({ capacityKwh: -3 }), small({ capacityKwh: 501 })]);
  rec("learnedCap", () => [small({ targetSocPct: 70, learnedCapacityKwh: 36 }), small({ targetSocPct: 70, learnedCapacityKwh: 20 })]);
  rec("noNeedEqual", () => [small({ socPct: 80 }), small({ socPct: 79 }), small({ socPct: 100, targetSocPct: 100 })]);
  rec("windowOver", () => [small({ elapsedMin: 300 }), small({ elapsedMin: 299 }), small({ elapsedMin: 301 }), small({ elapsedMin: -721 })]);
  rec("beforeWindow", () => night({ elapsedMin: -90, preWindowDrainW: 0, actuatorProfile: "RATE_CONTROLLER_PROPOSED" }));
  rec("drain", () => [night({ elapsedMin: -150, socPct: 30, targetSocPct: 90, preWindowDrainW: 600 }), night({ elapsedMin: -150, socPct: 30, targetSocPct: 90, preWindowDrainW: 600, socAgeMin: 15 }),
    small({ elapsedMin: -150, socPct: 30, targetSocPct: 90 }), small({ elapsedMin: -10, socPct: 85, preWindowDrainW: 0 }), small({ elapsedMin: -90, preWindowDrainW: -1 }), small({ preWindowDrainW: 5000 })]);
  rec("deadlinePassed", () => [night({ elapsedMin: 250, socPct: 70, inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } }), night({ elapsedMin: 250, socPct: 70, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } })]);
  rec("dwell", () => [night({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 80, changesUsed: 0 } }), night({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 70, changesUsed: 0 } })]);
  rec("touDwell", () => night({ elapsedMin: 100, socPct: 40, actuatorProfile: "TOU_SLOT_EDITOR", inForce: { setpointW: 2000, lastChangeAtMin: 50, changesUsed: 0 } }));
  rec("budget", () => [night({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 6 } }), night({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 5 } }),
    night({ elapsedMin: 100, socPct: 40, actuatorProfile: "TOU_SLOT_EDITOR", inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 1 } })]);
  rec("pathFixed", () => night({ elapsedMin: 100, socPct: 40, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } }));
  rec("pastKnee", () => [night({ elapsedMin: 100, socPct: 93, targetSocPct: 95, inForce: { setpointW: 5200, lastChangeAtMin: 0, changesUsed: 0 } }), night({ elapsedMin: 100, socPct: 91, targetSocPct: 95, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } }),
    night({ elapsedMin: 100, socPct: 90, targetSocPct: 95, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } })]);
  rec("kneeOptimistic", () => [night({ elapsedMin: 5, socPct: 90, targetSocPct: 95, inForce: f2000 }), night({ elapsedMin: 5, socPct: 89, targetSocPct: 95, inForce: f2000 }), night({ elapsedMin: 5, socPct: 88.9, targetSocPct: 95, inForce: f2000 }),
    night({ elapsedMin: 5, socPct: 89.6, targetSocPct: 95, inForce: f2000 }), night({ elapsedMin: 5, socPct: 89.5, targetSocPct: 90, inForce: f2000 })]);
  rec("kneeAnchor", () => [night({ elapsedMin: 100, socPct: 93, targetSocPct: 95, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } }), night({ elapsedMin: 100, socPct: 93, targetSocPct: 95 })]);
  rec("forced", () => night({ elapsedMin: 100, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 99, changesUsed: 6 } }));
  rec("forcedBudget", () => [night({ elapsedMin: 100, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 2 } }),
    night({ elapsedMin: 100, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 7000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 5 } })]);
  rec("stopFixed", () => [night({ elapsedMin: 60, socPct: 40, actuatorProfile: "FREE_POWER_LEASE", ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } }),
    night({ elapsedMin: 60, socPct: 40, actuatorProfile: "TOU_SLOT_EDITOR", ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 1 } })]);
  rec("inForceZero", () => [night({ elapsedMin: 60, socPct: 40, inForce: { setpointW: 0, lastChangeAtMin: 0, changesUsed: 0 } }), night({ elapsedMin: 60, socPct: 92, targetSocPct: 95, inForce: { setpointW: 0, lastChangeAtMin: 0, changesUsed: 0 } })]);
  rec("inForceInvalid", () => [small({ elapsedMin: 60, socPct: 40, inForce: { setpointW: 300, lastChangeAtMin: 0, changesUsed: 0 } }), small({ elapsedMin: 60, socPct: 40, inForce: { setpointW: 2050, lastChangeAtMin: 0, changesUsed: 0 } }),
    small({ inForce: { setpointW: -100, lastChangeAtMin: 0, changesUsed: 0 } }), night({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 8050, lastChangeAtMin: 0, changesUsed: 0 } })]);
  rec("hysteresis", () => [night({ elapsedMin: 100, socPct: 60, inForce: { setpointW: 4000, lastChangeAtMin: 0, changesUsed: 0 } }), night({ elapsedMin: 100, socPct: 60, inForce: { setpointW: 6500, lastChangeAtMin: 0, changesUsed: 0 } })]);
  rec("raise", () => [night({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } }), night({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 6700, lastChangeAtMin: 0, changesUsed: 0 } })]);
  rec("relies", () => night({ targetSocPct: 60, inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 } }));
  rec("touRelies", () => night({ socPct: 30, targetSocPct: 90, actuatorProfile: "TOU_SLOT_EDITOR", inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 } }));
  rec("boundary", () => [night({ capacityKwh: 31.3, targetSocPct: 60, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 } }),
    night({ capacityKwh: 31.4, targetSocPct: 60, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 } }), small({ capacityKwh: 31.4, targetSocPct: 60 }), small({ capacityKwh: 31.3, targetSocPct: 60 })]);
  rec("slotTable", () => [m.windowFromSlotTable([slot(60, 5000, 90, "Grid"), null as never, slot(180, 5000, 15, "None")]), m.windowFromSlotTable([slot(23 * 60 + 30, 5000, 90, "Grid"), slot(5 * 60, 5000, 15, "None"), slot(9 * 60, 5000, 15, "None")]),
    m.windowFromSlotTable([slot(60, 5000, 90, "Grid"), slot(120, 5000, 15, "None"), slot(180, 5000, 90, "Grid"), slot(240, 5000, 15, "None")]),
    m.windowFromSlotTable([slot(60, 5000, 90, "Grid"), slot(120, 6000, 90, "Grid"), slot(180, 5000, 15, "None"), slot(900, 5000, 15, "None")]),
    m.windowFromSlotTable([slot(60, 5000, 90, "Grid"), slot(120, 5000, 90, "Grid"), slot(180, 5000, 15, "None"), slot(900, 5000, 15, "None")]),
    m.windowFromSlotTable([slot(0, 5000, 15, "None"), slot(600, 5000, 15, "None")]), m.windowFromSlotTable([slot(0, 5000, 15, "Grid"), slot(600, 5000, 15, "Grid")])]);
  return out;
}

export interface Mutant {
  id: string;
  from: string;
  to: string;
  /** Probe keys of which at least one must differ from the committed golden. */
  keys: string[];
}

export const MUTANTS: readonly Mutant[] = [
  { id: "the default buffer is 0, not 60", from: "input.bufferMin === undefined ? 60 : input.bufferMin;", to: "input.bufferMin === undefined ? 0 : input.bufferMin;", keys: ["deadlineDefault"] },
  { id: "the 5 minute step of the buffer is not checked", from: "buffer > 120 || buffer % 5 !== 0", to: "buffer > 120", keys: ["bufferStep"] },
  { id: "the buffer may be 125", from: "buffer < 0 || buffer > 120 ||", to: "buffer < 0 || buffer > 125 ||", keys: ["bufferMax"] },
  { id: "the buffer may be negative", from: "buffer < 0 || buffer > 120 ||", to: "buffer > 120 ||", keys: ["bufferMax"] },
  { id: "a target of 5 is accepted", from: "target < 10 || target > 100", to: "target < 1 || target > 100", keys: ["targetBounds"] },
  { id: "a target above 100 is accepted", from: "target < 10 || target > 100", to: "target < 10 || target > 101", keys: ["targetBounds"] },
  { id: "the clock change is refused only when the window starts before it", from: "return span(rangeStart, startMin) <= 120 || span(startMin, rangeStart) <= wall;", to: "return span(startMin, rangeStart) <= wall;", keys: ["clockSpring", "clockAutumn", "clockPlan"] },
  { id: "the clock change is refused only when the window starts inside the hour", from: "return span(rangeStart, startMin) <= 120 || span(startMin, rangeStart) <= wall;", to: "return span(rangeStart, startMin) <= 120;", keys: ["clockSpring", "clockAutumn", "clockPlan"] },
  { id: "the refused range starts at the change, not an hour before", from: "const rangeStart = norm(day.changeAtMin - 60);", to: "const rangeStart = norm(day.changeAtMin);", keys: ["clockSpring", "clockAutumn"] },
  { id: "the edge of the repeated hour is not refused", from: "span(rangeStart, startMin) <= 120 ||", to: "span(rangeStart, startMin) < 120 ||", keys: ["clockSpring", "clockAutumn"] },
  { id: "an ordinary day is treated as a clock change day", from: "if (day.deltaMin === 0) return false;", to: "", keys: ["ordinaryDay", "A"] },
  { id: "the ceiling is the larger of the firmware bound and the owner limit", from: "let ceiling = Math.min(eff.best.watts, P.hardMaxW);", to: "let ceiling = Math.max(eff.best.watts, P.hardMaxW);", keys: ["ceilingMin"] },
  { id: "the ceiling is not floored to a step", from: "ceiling = floorStep(ceiling, P.stepW);", to: "ceiling = ceiling;", keys: ["ceilingStep"] },
  { id: "the lowest rate is the step, not 500 W", from: "const minW = ceilStep(P.minW, P.stepW);", to: "const minW = P.stepW;", keys: ["minRate", "ceilingBelowMin"] },
  { id: "a ceiling below the minimum is accepted", from: "if (ceiling < minW) return refuse(", to: "if (ceiling < 0) return refuse(", keys: ["ceilingBelowMin"] },
  { id: "no ceiling is accepted as no limit", from: "if (eff.best === null) return refuse(\"INPUTS_UNUSABLE\", [\"NO_SAFE_CEILING\"]);", to: "if (eff.best === null) eff.best = { watts: 8000, name: \"guess\" };", keys: ["noCeiling", "staleCeiling"] },
  { id: "a ceiling with an age beyond the limit counts as fresh", from: "effectiveCeiling(input.ceilings, P.maxCeilingAgeMin,", to: "effectiveCeiling(input.ceilings, 1e9,", keys: ["staleCeiling"] },
  { id: "R3: a GRID_AC ceiling is taken as a setpoint-side figure (not converted by 0.85)", from: "ceilingInSetpointUnits(x, \"UNSETTLED\",", to: "ceilingInSetpointUnits(x, \"GRID_AC\",", keys: ["gridAc"] },
  { id: "the grid cap ignores the overshoot allowance", from: "* P.setpointConversionEff) / P.setpointOvershoot);", to: "* P.setpointConversionEff) / 1);", keys: ["gridCap"] },
  { id: "the grid cap ignores the demand margin", from: "peak * (1 + P.demandMarginPct / 100)", to: "peak", keys: ["gridCap"] },
  { id: "R1: the grid cap applies only when it is 1000 W below the ceiling", from: "if (cap < ceiling) {", to: "if (cap < ceiling - 1000) {", keys: ["gridJustBelow"] },
  { id: "an unknown demand is read as zero", from: "if (!isNum(peak) || peak < 0 || !isNum(dage)", to: "if (!isNum(dage)", keys: ["demandUnknown"] },
  { id: "a stale demand is used", from: "dage < 0 || dage > P.maxHouseholdAgeMin", to: "dage < 0 || dage > 1e9", keys: ["demandStale"] },
  { id: "a stale grid limit is used", from: "lage > P.maxGridLimitAgeMin", to: "lage > 1e9", keys: ["gridStale"] },
  { id: "an unknown grid limit is not said to apply no cap", from: "if (gridLimit === undefined || gridLimit === null) codes.push(\"GRID_LIMIT_UNKNOWN_NO_CAP\");", to: "if (gridLimit === undefined || gridLimit === null) codes.push(\"AT_TARGET\");", keys: ["gridUnknownSaid", "A"] },
  { id: "a stale SOC is used", from: "age > P.maxSocAgeMin", to: "age > 1e9", keys: ["staleSoc"] },
  { id: "an unknown SOC age is accepted", from: "if (!isNum(age) || age < 0 ||", to: "if (age < 0 ||", keys: ["staleSoc"] },
  { id: "an unknown SOC is read as zero", from: "if (soc === null || soc === undefined || !isNum(soc)) return refuse(\"INPUTS_UNUSABLE\", [\"NO_SOC\"]);", to: "if (soc === undefined) return refuse(\"INPUTS_UNUSABLE\", [\"NO_SOC\"]);", keys: ["noSoc"] },
  { id: "a falling SOC reading is never implausible", from: "soc < prev.socPct - P.socRegressionTolPct ||", to: "false ||", keys: ["socRegression"] },
  { id: "a jump in the SOC reading is never implausible", from: "|| soc > prev.socPct + P.socResolutionPct + P.socRegressionTolPct + P.socJumpPctPerHour * hours", to: "|| false", keys: ["socJump"] },
  { id: "R7: a previous reading from the future is accepted", from: "|| prev.elapsedMin > elapsed)", to: ")", keys: ["prevFuture"] },
  { id: "a SOC above 100 is accepted", from: "if (soc < 0 || soc > 100) return refuse(", to: "if (soc < 0) return refuse(", keys: ["socRange"] },
  { id: "a zero capacity is accepted", from: "if (!isNum(nominal) || nominal <= 0 || nominal > 500)", to: "if (!isNum(nominal) || nominal > 500)", keys: ["capacityUnusable"] },
  { id: "the learned capacity is ignored", from: "Math.max(nominal, learned)", to: "nominal", keys: ["learnedCap"] },
  { id: "R8: a negative rate in force is accepted", from: "(!isNum(given0.setpointW) || given0.setpointW < 0)", to: "(!isNum(given0.setpointW))", keys: ["inForceInvalid"] },
  { id: "BLOCKER 3: a 0 W rate in force is a rate, not a START", from: "const force: NightInForce = given0.setpointW === 0 ?", to: "const force: NightInForce = false ?", keys: ["inForceZero"] },
  { id: "BLOCKER 3: a rate in force below the minimum is used", from: "(inW < minW - EPS ||", to: "(inW < 0 ||", keys: ["inForceInvalid"] },
  { id: "BLOCKER 3: a rate in force off the step is used", from: "|| Math.abs(inW / P.stepW - Math.round(inW / P.stepW)) > 1e-9)", to: "|| false)", keys: ["inForceInvalid"] },
  { id: "MAJOR 4: a missing drain bound before the window is taken as none (the SOC unchanged until the window opens)", from: "const drain = input.preWindowDrainW;", to: "const drain = input.preWindowDrainW ?? 0;", keys: ["drain"] },
  { id: "MAJOR 4: the drain before the window is ignored", from: "socPlan = Math.max(0, soc - (drain * (age - elapsed)) / 60 / 1000 / fewestKwhPerPct);", to: "socPlan = soc;", keys: ["drain"] },
  { id: "MAJOR 4: the drain ignores the reading's age", from: "(drain * (age - elapsed))", to: "(drain * (0 - elapsed))", keys: ["drain"] },
  { id: "MAJOR 4: the drain is counted in the trusted capacity, not the fewest kWh per point", from: "const fewestKwhPerPct = (capKwh * (1 - P.capacityBandPct / 100)) / (1 + P.socScaleErrPct / 100) / 100;", to: "const fewestKwhPerPct = capKwh / 100;", keys: ["drain"] },
  { id: "a battery exactly at the target still has something to charge", from: "if (socPlan >= target) {", to: "if (socPlan > target) {", keys: ["noNeedEqual"] },
  { id: "a window that has just ended is still planned", from: "if (elapsed >= W) return refuse(", to: "if (elapsed > W) return refuse(", keys: ["windowOver"] },
  { id: "MAJOR 5: with no path named the generic model is assumed", from: ": \"FREE_POWER_LEASE\";", to: ": \"UNCONSTRAINED\";", keys: ["defaultProfile"] },
  { id: "MAJOR 5: the assumed default path is not said", from: "if (!profileNamed) codes.push(\"PROFILE_DEFAULT_MOST_RESTRICTIVE\");", to: "", keys: ["defaultProfile"] },
  { id: "the pessimistic efficiency is the expected one", from: "P.chargeEffMin, kneeP, P.tailFraction", to: "P.chargeEff, kneeP, P.tailFraction", keys: ["A", "A60", "B"] },
  { id: "the pessimistic capacity band is taken downwards", from: "(capKwh * (1 + band)) / (1 - scale) / 100", to: "(capKwh * (1 - band)) / (1 - scale) / 100", keys: ["A", "A60"] },
  { id: "the sensor scale error is taken the optimistic way in the pessimistic world", from: "(capKwh * (1 + band)) / (1 - scale) / 100", to: "(capKwh * (1 + band)) / (1 + scale) / 100", keys: ["A", "A60"] },
  { id: "the pessimistic start ignores the reading noise", from: "-(P.socResolutionPct / 2 + P.socNoisePct)", to: "-(P.socResolutionPct / 2)", keys: ["A", "A60"] },
  { id: "the pessimistic knee is the expected knee", from: "P.chargeEffMin, kneeP, P.tailFraction", to: "P.chargeEffMin, kneeP + P.kneeSpreadPct, P.tailFraction", keys: ["B", "C", "F"] },
  { id: "the pessimistic tail is the expected tail", from: "kneeP, P.tailFraction, Math.min(1, P.dropMin)", to: "kneeP, P.tailFractionExpected, Math.min(1, P.dropMin)", keys: ["B", "C", "C93", "F"] },
  { id: "the pessimistic fall is not a cliff", from: "P.tailFraction, Math.min(1, P.dropMin)", to: "P.tailFraction, P.dropMin", keys: ["C", "C93", "B"] },
  { id: "the plateau has no knee", from: "if (st.soc + perMin * dt >= w.knee - EPS && w.knee < 100) {", to: "if (false) {", keys: ["B", "C", "C93", "F"] },
  { id: "the tail is anchored to the current setpoint instead of the one at the knee", from: "const tr = Math.min(1, (w.tail * st.kneeW) / rateW);", to: "const tr = w.tail;", keys: ["kneeAnchor", "D", "C"] },
  { id: "a start past the knee is treated as still on the plateau of a fall that has not begun", from: "kneeAt: past ? t - w.dropMin - 1 : null", to: "kneeAt: past ? t : null", keys: ["D", "pastKnee"] },
  { id: "R6: the anchor of a start past the knee is lost (the rate tried becomes the anchor)", from: "kneeW: past ? anchor : null", to: "kneeW: null", keys: ["kneeAnchor", "D"] },
  { id: "BLOCKER 1: the knee is decided from the pessimistic start, not the optimistic estimate (the reviewed rule)", from: "return c.target > c.pess.knee + EPS && reading + c.upOffset >= c.pess.knee - EPS;", to: "return reading + c.pess.offset >= c.pess.knee - EPS;", keys: ["kneeOptimistic"] },
  { id: "R10: the knee threshold is exclusive", from: "reading + c.upOffset >= c.pess.knee - EPS", to: "reading + c.upOffset > c.pess.knee + EPS", keys: ["kneeOptimistic"] },
  { id: "BLOCKER 1: the optimistic estimate ignores the reading noise", from: "upOffset: P.socResolutionPct / 2 + P.socNoisePct,", to: "upOffset: P.socResolutionPct / 2,", keys: ["kneeOptimistic"] },
  { id: "BLOCKER 1: the hold also applies to a target at or below the knee", from: "return c.target > c.pess.knee + EPS && reading", to: "return reading", keys: ["kneeOptimistic"] },
  { id: "BLOCKER 1: a raise inside the reading uncertainty is credited (the tail anchored at the rate tried)", from: "isPess ? Math.min(inForceW, rateW) : inForceW", to: "isPess ? rateW : inForceW", keys: ["kneeAnchor"] },
  { id: "the optimistic world uses the pessimistic efficiency", from: "P.chargeEffMax, kneeAbove(2 * P.kneeSpreadPct)", to: "P.chargeEffMin, kneeAbove(2 * P.kneeSpreadPct)", keys: ["A", "A60", "B"] },
  { id: "the expected knee is the pessimistic knee", from: "kneeAbove(P.kneeSpreadPct), P.tailFractionExpected", to: "kneeP, P.tailFractionExpected", keys: ["B", "C", "F"] },
  { id: "OK is judged against the window end, not the deadline", from: "const basisOk = pf !== null && pf <= deadline + EPS;", to: "const basisOk = pf !== null && pf <= W + EPS;", keys: ["F", "B", "E"] },
  { id: "R2: OK with a two minute miss", from: "const basisOk = pf !== null && pf <= deadline + EPS;", to: "const basisOk = pf !== null && pf <= deadline + 2;", keys: ["boundary"] },
  { id: "R12: the needed-rate search accepts a two minute miss", from: "const need = lowestFeasible(c, simT, reading, cur, c.deadline);", to: "const need = lowestFeasible(c, simT, reading, cur, c.deadline + 2);", keys: ["boundary"] },
  { id: "MAJOR 5: the status is judged on the planned projection again (OK may rely on a later change)", from: "const pf = ph.outcome.finishMin;", to: "const pf = pp.outcome.finishMin;", keys: ["touRelies", "relies"] },
  { id: "a miss inside the buffer is not AT_RISK", from: "|| (pf !== null && pf <= W + EPS)) status = \"TARGET_AT_RISK\";", to: "|| false) status = \"TARGET_AT_RISK\";", keys: ["deadlinePassed"] },
  { id: "an unreachable target is called at risk", from: "else status = \"UNREACHABLE\";", to: "else status = \"TARGET_AT_RISK\";", keys: ["E"] },
  { id: "a later change that the pessimistic world relies on is not reported", from: "if (plannedOk && !basisOk) codes.push(\"RELIES_ON_LATER_CHANGE\");", to: "", keys: ["relies", "touRelies"] },
  { id: "planned later points are not marked conditional", from: "segments.push({ atMin: tk, inMin: tk - now, setpointW: ch.rateW, change: ch.change, conditional: true });", to: "segments.push({ atMin: tk, inMin: tk - now, setpointW: ch.rateW, change: ch.change, conditional: false });", keys: ["RC", "TOU"] },
  { id: "the editor's dwell is the generic one", from: "dwellMin: tightened.dwellMin,", to: "dwellMin: merged.dwellMin,", keys: ["touDwell", "TOU"] },
  { id: "the editor's change budget is the generic one", from: "maxChanges: tightened.maxChanges }", to: "maxChanges: merged.maxChanges }", keys: ["budget", "TOU"] },
  { id: "the dwell is not enforced", from: "f.lastChangeAtMin === null || now - f.lastChangeAtMin >= c.dwell - EPS;", to: "true;", keys: ["dwell", "touDwell"] },
  { id: "the change budget is off by one", from: "const budgetOk = f.changesUsed < c.maxChanges;", to: "const budgetOk = f.changesUsed <= c.maxChanges;", keys: ["budget"] },
  { id: "the rate is changed after the knee", from: "const canChange = pathOk && budgetOk && dwellOk && !pastKnee;", to: "const canChange = pathOk && budgetOk && dwellOk;", keys: ["pastKnee", "kneeOptimistic"] },
  { id: "a path that cannot change is allowed to", from: "const pathOk = c.midWindow && c.maxChanges > 0;", to: "const pathOk = true;", keys: ["pathFixed"] },
  { id: "a rate above the ceiling is kept", from: "const cur = f.setpointW === null ? null : Math.min(f.setpointW, c.ceilingW);", to: "const cur = f.setpointW;", keys: ["forced"] },
  { id: "BLOCKER 2: a fixed path is lowered to the ceiling instead of stopping", from: "if (c.fixedPath) {", to: "if (false) {", keys: ["stopFixed"] },
  { id: "BLOCKER 2: a path that can change is stopped too", from: "fixedPath: !profile.midWindowAdjustment,", to: "fixedPath: true,", keys: ["stopFixed", "forced"] },
  { id: "BLOCKER 2: the band of a STOP is for the ceiling, not the rate in force", from: "return { rateW: f.setpointW, change: \"STOP\",", to: "return { rateW: c.ceilingW, change: \"STOP\",", keys: ["stopFixed"] },
  { id: "BLOCKER 2: a STOP still carries a trajectory", from: "trajectory: stop ? [] :", to: "trajectory:", keys: ["stopFixed"] },
  { id: "R11: a forced decrease draws on the budget in the projection", from: "const drawsBudget = (first.change === \"INCREASE\" || first.change === \"DECREASE\") && !forcedOnly;", to: "const drawsBudget = first.change === \"INCREASE\" || first.change === \"DECREASE\";", keys: ["forcedBudget"] },
  { id: "R11: a forced decrease draws on the budget in the report", from: " && !(first.codes.includes(\"FORCED_BELOW_CEILING\") && first.rateW === ceiling)", to: "", keys: ["forcedBudget"] },
  { id: "any decrease is taken, whatever it saves", from: "if (held - lowRate >= c.hysteresis - EPS && lowRate >= c.minW) {", to: "if (held - lowRate > 0 && lowRate >= c.minW) {", keys: ["hysteresis"] },
  { id: "a decrease keeps no slack to the deadline", from: "const low = lowestFeasible(c, simT, reading, held, c.deadline - c.slack);", to: "const low = lowestFeasible(c, simT, reading, held, c.deadline);", keys: ["hysteresis", "RC"] },
  { id: "a needed raise is never made", from: "if (need.rateW > held) {", to: "if (need.rateW > held + 100000) {", keys: ["raise", "deadlinePassed"] },
  { id: "the search never offers the lowest candidate", from: "let lo = 0;", to: "let lo = 1;", keys: ["minRate"] },
  { id: "before the window the simulation starts in the past", from: "const first = choose(ctx, socPlan, Math.max(elapsed, 0), elapsed, force);", to: "const first = choose(ctx, socPlan, elapsed, elapsed, force);", keys: ["beforeWindow"] },
  { id: "before the window the trajectory starts now", from: "const t0 = Math.max(now, 0);", to: "const t0 = now;", keys: ["beforeWindow"] },
  { id: "the SOC at the deadline is reported as the target", from: "socAtDeadline = st.soc;", to: "socAtDeadline = c.target;", keys: ["B", "E", "F"] },
  { id: "the margin is reported the wrong way round", from: "Math.round((deadline - pf) * 10) / 10", to: "Math.round((pf - deadline) * 10) / 10", keys: ["A", "A60"] },
  { id: "the buffer that would fit rounds up", from: "Math.floor((W - pf) / 5 + EPS) * 5", to: "Math.ceil((W - pf) / 5 - EPS) * 5", keys: ["F", "B"] },
  { id: "the wall-clock finish forgets the window start", from: "wallClock: fmt(startMin + Math.round(ef))", to: "wallClock: fmt(Math.round(ef))", keys: ["A", "RC"] },
  { id: "two separate runs of grid slots are not ambiguous", from: "if (runStarts !== 1) return null;", to: "if (runStarts < 1) return null;", keys: ["slotTable"] },
  { id: "slots of a run that disagree are not ambiguous", from: "if (run.some((s) => s.powerW !== head.powerW || s.targetSoc !== head.targetSoc)) return null;", to: "", keys: ["slotTable"] },
  { id: "the window ends where it starts", from: "endMin: after.startMin,", to: "endMin: head.startMin,", keys: ["slotTable"] },
  { id: "a slot table with an unusable entry still has a window", from: "if (n !== slots.length) return null;", to: "", keys: ["slotTable"] },
];
