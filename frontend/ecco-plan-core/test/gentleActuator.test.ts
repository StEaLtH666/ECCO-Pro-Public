// Gentle model, 24 Nov 2026: the resolved charge-rate limits and the actuator constraints (offline evidence). READ ONLY: these tests drive a pure function.
// Facts under test: one authoritative maximum-charge-power basis; the path profiles (a rate fixed at the START, a guarded slot editor with the owner's
// confirmation per write, a controller that does not exist); the overshoot allowance; the finish-early default of 60 minutes; the unreachable target.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import {
  planGentle, applyActuatorProfile, maxChargePowerCeiling, setpointScale, ceilingInSetpointUnits, DEFAULT_GENTLE_PARAMS, DEFAULT_GENTLE_POLICY, GENTLE_RECOMMENDED_PARAMS,
  GENTLE_ACTUATOR_PROFILES, MAX_CHARGE_POWER_BASIS, MAX_CHARGE_POWER_NAME, GENTLE_DEFAULT_BUFFER_MIN, PARAM_PROVENANCE, CONTROLLER_LABEL,
} from "../src/gentleController.ts";
import type { GentleInput, GentleParams, ActuatorProfileId } from "../src/gentleController.ts";
import { LIMITS } from "../src/settings.ts";

const ORDINARY = { changeAtMin: 0, deltaMin: 0 };
const base: GentleInput = {
  targetSocPct: 80, bufferMin: 60, chargeWindow: { startMin: 22 * 60, endMin: 4 * 60, clockDay: ORDINARY }, elapsedMin: 0, socPct: 20, socAgeMin: 1,
  capacityKwh: 30, capacityUpPct: 6, ceilings: [maxChargePowerCeiling(8000, 8000)], currentSetpointW: null, lastChangeElapsedMin: null, changesUsed: 0,
};
type Mod = { planGentle: typeof planGentle; applyActuatorProfile: typeof applyActuatorProfile; maxChargePowerCeiling: typeof maxChargePowerCeiling; DEFAULT_GENTLE_PARAMS: typeof DEFAULT_GENTLE_PARAMS };
const planWith = (m: Mod, profile: ActuatorProfileId, over: Partial<GentleInput> = {}, params: Partial<GentleParams> = {}) =>
  m.planGentle({ ...base, ...over, params: { ...(over.params ?? {}), ...params }, policy: { actuatorProfile: profile } });
const here: Mod = { planGentle, applyActuatorProfile, maxChargePowerCeiling, DEFAULT_GENTLE_PARAMS };

// A later tick in a night: the START rate and then a reading far BELOW the plan (a lost charge) or far ABOVE it.
const startRate = (m: Mod, profile: ActuatorProfileId): number => planWith(m, profile).setpointW as number;
const late = (m: Mod, profile: ActuatorProfileId, soc: number, elapsedMin: number, changesUsed = 0) =>
  planWith(m, profile, { socPct: soc, elapsedMin, currentSetpointW: startRate(m, "UNCONSTRAINED"), lastChangeElapsedMin: 0, changesUsed });

test("the one authoritative maximum-charge-power basis: a setpoint bound, the smaller of the firmware bound and the owner's limit, never guessed", () => {
  assert.equal(MAX_CHARGE_POWER_BASIS.authoritativeW, LIMITS.chargePowerMax);
  assert.equal(MAX_CHARGE_POWER_BASIS.kind, "SETPOINT_BOUND");
  assert.equal(MAX_CHARGE_POWER_BASIS.name, MAX_CHARGE_POWER_NAME);
  assert.ok(Object.isFrozen(MAX_CHARGE_POWER_BASIS) && Object.isFrozen(MAX_CHARGE_POWER_BASIS.isNot));
  assert.equal(MAX_CHARGE_POWER_BASIS.isNot.length, 4, "it says what it is NOT: a measured power, the grid limit, the rated power, a BMS limit");
  assert.match(MAX_CHARGE_POWER_BASIS.source, /firmware/);
  assert.deepEqual(maxChargePowerCeiling(8000, 5000), { name: MAX_CHARGE_POWER_NAME, watts: 5000 });
  assert.deepEqual(maxChargePowerCeiling(8000, 65500), { name: MAX_CHARGE_POWER_NAME, watts: 8000 }, "the helper's loose default does not raise it");
  assert.deepEqual(maxChargePowerCeiling(5000, 8000), { name: MAX_CHARGE_POWER_NAME, watts: 5000 });
  for (const bad of [null, undefined, NaN, -1, Infinity]) {
    assert.equal(maxChargePowerCeiling(bad as number, 8000).watts, null, "an unknown firmware bound is unknown, never guessed: " + String(bad));
    assert.equal(maxChargePowerCeiling(8000, bad as number).watts, null, "an unknown operating limit is unknown, never guessed: " + String(bad));
  }
  assert.equal(maxChargePowerCeiling(8000, 8000, 7).ageMin, 7);
  assert.equal("ageMin" in maxChargePowerCeiling(8000, 8000), false);
  // used as the ceiling: the plan is capped at it and says which ceiling set it
  const d = planWith(here, "UNCONSTRAINED", { ceilings: [maxChargePowerCeiling(8000, 3000)], targetSocPct: 100, socPct: 10 });
  assert.equal(d.ceilingW, 3000);
  assert.equal(d.ceilingName, MAX_CHARGE_POWER_NAME);
});

test("the actuator profiles: each states its step, range, dwell and adjustments; none is authorised; the fixed-rate path allows no adjustment", () => {
  const ids = Object.keys(GENTLE_ACTUATOR_PROFILES) as ActuatorProfileId[];
  assert.deepEqual(ids.sort(), ["FREE_POWER_LEASE", "RATE_CONTROLLER_PROPOSED", "TOU_SLOT_EDITOR", "UNCONSTRAINED"]);
  assert.ok(Object.isFrozen(GENTLE_ACTUATOR_PROFILES) && Object.isFrozen(GENTLE_ACTUATOR_PROFILES.FREE_POWER_LEASE));
  for (const id of ids) {
    const a = GENTLE_ACTUATOR_PROFILES[id];
    assert.equal(a.id, id);
    assert.equal(a.automaticApplyAuthorised, false, id + " is not authorised to apply anything");
    assert.equal(a.stepW, 100);
    assert.ok(a.minW >= 500 && a.maxW <= LIMITS.chargePowerMax && a.minW <= a.maxW, id + " range");
    assert.ok(a.limitation.length > 20 && a.source.length > 10 && a.confidence.length > 3, id + " carries its limitation, source and confidence");
  }
  const f = GENTLE_ACTUATOR_PROFILES.FREE_POWER_LEASE;
  assert.deepEqual([f.midWindowAdjustment, f.maxAdjustmentsPerWindow, f.existsToday, f.ownerConfirmationPerChange], [false, 0, true, false]);
  const t = GENTLE_ACTUATOR_PROFILES.TOU_SLOT_EDITOR;
  assert.deepEqual([t.midWindowAdjustment, t.maxAdjustmentsPerWindow, t.minDwellMin, t.existsToday, t.ownerConfirmationPerChange], [true, 1, 60, true, true]);
  const r = GENTLE_ACTUATOR_PROFILES.RATE_CONTROLLER_PROPOSED;
  assert.deepEqual([r.existsToday, r.maxAdjustmentsPerWindow, r.minDwellMin], [false, DEFAULT_GENTLE_PARAMS.maxChanges, DEFAULT_GENTLE_PARAMS.dwellMin]);
  assert.equal(DEFAULT_GENTLE_POLICY.actuatorProfile, "UNCONSTRAINED", "no path is assumed unless the owner names one");
});

test("applying a profile: the stricter value wins and a profile never loosens a parameter", () => {
  const P = { ...DEFAULT_GENTLE_PARAMS };
  const u = applyActuatorProfile(P, "UNCONSTRAINED");
  assert.deepEqual(u.params, P);
  assert.deepEqual(u.tightened, []);
  const t = applyActuatorProfile(P, "TOU_SLOT_EDITOR");
  assert.equal(t.params.dwellMin, 60);
  assert.equal(t.params.maxChanges, 1);
  assert.deepEqual(t.tightened.sort(), ["dwellMin", "maxChanges"]);
  const f = applyActuatorProfile(P, "FREE_POWER_LEASE");
  assert.equal(f.params.maxChanges, 0);
  assert.equal(f.params.dwellMin, DEFAULT_GENTLE_PARAMS.dwellMin, "a fixed-rate path has no dwell of its own: the model's own dwell stays");
  const strict = applyActuatorProfile({ ...P, dwellMin: 90, maxChanges: 0, hardMaxW: 6000 }, "TOU_SLOT_EDITOR");
  assert.deepEqual([strict.params.dwellMin, strict.params.maxChanges, strict.params.hardMaxW], [90, 0, 6000], "the caller's stricter values stay");
  assert.equal(applyActuatorProfile({ ...P, hardMaxW: 9000 }, "TOU_SLOT_EDITOR").params.hardMaxW, LIMITS.chargePowerMax, "a range wider than the path allows is cut to it");
  const low = applyActuatorProfile({ ...P, minW: 300 }, "TOU_SLOT_EDITOR");
  assert.equal(low.params.minW, 500);
  const odd = applyActuatorProfile({ ...P, stepW: 150 }, "TOU_SLOT_EDITOR");
  assert.equal(odd.params.stepW, 200, "a step that is not a multiple of the path's granularity is raised to one");
  assert.ok(odd.tightened.includes("stepW"));
});

test("a fixed-rate path (Free Power): the START is the lowest constant rate; nothing is adjusted afterwards; a shortfall and a safety decrease are said plainly", () => {
  const s0 = planWith(here, "FREE_POWER_LEASE");
  const free = s0.setpointW as number;
  assert.equal(s0.change, "START");
  assert.equal(free, startRate(here, "UNCONSTRAINED"), "the START rate is the generic lowest feasible rate");
  assert.equal(s0.actuator.profile, "FREE_POWER_LEASE");
  assert.deepEqual([s0.actuator.midWindowAdjustment, s0.actuator.maxAdjustmentsPerWindow, s0.changesLeft, s0.actuator.applicableNow], [false, 0, 0, true]);
  assert.equal(s0.actuator.automaticApplyAuthorised, false);
  assert.equal(s0.actuationSupported, false);
  assert.equal(s0.label, CONTROLLER_LABEL);
  // a reading far below the plan: the generic model would raise the rate; the fixed-rate path cannot, and says so
  const gen = late(here, "UNCONSTRAINED", 20, 150);
  assert.equal(gen.change, "INCREASE");
  assert.equal(gen.actuator.applicableNow, true);
  const fix = late(here, "FREE_POWER_LEASE", 20, 150);
  assert.equal(fix.change, "NONE");
  assert.ok(fix.codes.includes("HELD_BUDGET") && fix.codes.includes("ACTUATOR_FIXED_RATE") && fix.codes.includes("TARGET_AT_RISK"));
  assert.equal(fix.status, "TARGET_AT_RISK");
  assert.equal(fix.setpointW, free, "the rate in force is kept");
  assert.equal(fix.targetSocPct, 80, "the target is never lowered");
  assert.match(fix.reasons.join(" "), /fixed at the START/);
  // the ceiling falls below the rate in force: the lower rate cannot be applied on this path, so a stop is recommended
  const cut = planWith(here, "FREE_POWER_LEASE", { currentSetpointW: free, lastChangeElapsedMin: 0, elapsedMin: 30, socPct: 25, ceilings: [maxChargePowerCeiling(8000, free - 1000)] });
  assert.equal(cut.change, "DECREASE");
  assert.deepEqual([cut.actuator.applicableNow, cut.stopRecommended], [false, true]);
  assert.ok(cut.codes.includes("ACTUATOR_FIXED_RATE") && cut.codes.includes("ABOVE_CEILING"));
  const cutGeneric = planWith(here, "UNCONSTRAINED", { currentSetpointW: free, lastChangeElapsedMin: 0, elapsedMin: 30, socPct: 25, ceilings: [maxChargePowerCeiling(8000, free - 1000)] });
  assert.deepEqual([cutGeneric.actuator.applicableNow, cutGeneric.stopRecommended], [true, false]);
});

test("the guarded slot editor: one coarse adjustment per window at most, a 60 minute dwell, and the owner confirms the write", () => {
  const t0 = planWith(here, "TOU_SLOT_EDITOR");
  assert.deepEqual([t0.change, t0.actuator.maxAdjustmentsPerWindow, t0.actuator.minDwellMin, t0.actuator.ownerConfirmationPerChange, t0.changesLeft], ["START", 1, 60, true, 1]);
  assert.deepEqual(t0.actuator.tightened.sort(), ["dwellMin", "maxChanges"]);
  assert.deepEqual(t0.actuator.rangeW, [500, 8000]);
  // one increase for the deadline is allowed; a second is held by the budget and the miss is flagged, never papered over
  const inc = late(here, "TOU_SLOT_EDITOR", 20, 150);
  assert.equal(inc.change, "INCREASE");
  assert.deepEqual([inc.changesUsed, inc.changesLeft, inc.actuator.applicableNow], [1, 0, true]);
  const second = late(here, "TOU_SLOT_EDITOR", 20, 200, 1);
  assert.ok(second.codes.includes("HELD_BUDGET") && second.codes.includes("TARGET_AT_RISK"));
  assert.equal(second.actuator.applicableNow, null, "no change is recommended, so nothing to apply");
  // a saving: the generic 30 minute dwell lets it through at minute 40, the editor's 60 minute dwell holds it
  const gen = late(here, "UNCONSTRAINED", 50, 40);
  assert.equal(gen.change, "DECREASE");
  const held = late(here, "TOU_SLOT_EDITOR", 50, 40);
  assert.equal(held.change, "NONE");
  assert.ok(held.codes.includes("HELD_DWELL"));
  const ok = late(here, "TOU_SLOT_EDITOR", 50, 61);
  assert.equal(ok.change, "DECREASE", "after the dwell the saving is allowed");
});

test("the finish-early default is 60 minutes, configurable in 5 minute steps from 0 to 120; the target is never lowered when it cannot be reached", () => {
  assert.equal(GENTLE_DEFAULT_BUFFER_MIN, 60);
  const withNone = planGentle({ ...base, bufferMin: undefined });
  const with60 = planGentle({ ...base, bufferMin: 60 });
  assert.deepEqual(withNone, with60, "no buffer given = 60 minutes");
  assert.equal(withNone.deadlineInMin, 360 - 60);
  const w30 = planGentle({ ...base, bufferMin: 30 });
  assert.equal(w30.deadlineInMin, 330);
  assert.ok((w30.setpointW as number) <= (with60.setpointW as number), "a later deadline never needs a higher rate");
  assert.equal(planGentle({ ...base, bufferMin: 0 }).deadlineInMin, 360);
  for (const bad of [7, -5, 125, null as unknown as number, NaN]) assert.equal(planGentle({ ...base, bufferMin: bad }).status, "INVALID", String(bad));
  // unreachable: 10 % to 100 % in a 90 minute window with a 60 minute buffer and a 3000 W ceiling
  const tight = (profile: ActuatorProfileId) => planWith(here, profile, { targetSocPct: 100, socPct: 10, chargeWindow: { startMin: 22 * 60, endMin: 23 * 60 + 30, clockDay: ORDINARY }, ceilings: [maxChargePowerCeiling(8000, 3000)] });
  const u = tight("UNCONSTRAINED");
  assert.ok(u.status === "TARGET_AT_RISK" || u.status === "TARGET_UNREACHABLE");
  assert.equal(u.setpointW, 3000, "the best effort is the highest safe rate");
  assert.equal(u.targetSocPct, 100, "the target is never lowered");
  assert.equal(u.guarantee, "NONE");
  assert.equal(u.codes.includes("ACTUATOR_FIXED_RATE"), false);
  const f = tight("FREE_POWER_LEASE");
  assert.equal(f.setpointW, 3000);
  assert.ok(f.codes.includes("ACTUATOR_FIXED_RATE"), "a fixed-rate path says a shortfall cannot be repaired inside the window");
});

test("the overshoot allowance: the realised power was above the setpoint, so converted caps keep S times the factor inside the limit (off by default)", () => {
  assert.equal(DEFAULT_GENTLE_PARAMS.setpointOvershoot, 1);
  assert.equal(GENTLE_RECOMMENDED_PARAMS.setpointOvershoot, 1.1);
  assert.equal(PARAM_PROVENANCE.setpointOvershoot?.kind, "PROVISIONAL");
  assert.equal(PARAM_PROVENANCE.actuatorProfile?.kind, "PROVISIONAL");
  assert.ok(Math.abs(setpointScale("UNSETTLED", 0.85, 1.1) - 0.85 / 1.1) < 1e-12);
  assert.ok(Math.abs(setpointScale("GRID_AC", 0.85, 1.1) - 1 / 1.1) < 1e-12);
  assert.equal(setpointScale("GRID_AC", 0.85), 1, "off: the v1 scale");
  const dc = { name: "battery_limit", watts: 8000, basis: "BATTERY_DC" as const };
  assert.equal(ceilingInSetpointUnits(dc, "UNSETTLED", 0.85), 8000);
  assert.ok(Math.abs(ceilingInSetpointUnits(dc, "UNSETTLED", 0.85, 1.1) - 8000 / 1.1) < 1e-9);
  assert.equal(ceilingInSetpointUnits({ name: "setpoint_bound", watts: 8000 }, "UNSETTLED", 0.85, 1.1), 8000, "the setpoint bound itself is already in setpoint units");
  const off = planWith(here, "UNCONSTRAINED", { ceilings: [dc], targetSocPct: 100, socPct: 5 });
  const on = planWith(here, "UNCONSTRAINED", { ceilings: [dc], targetSocPct: 100, socPct: 5 }, { setpointOvershoot: 1.1 });
  assert.equal(off.ceilingW, 8000);
  assert.equal(on.ceilingW, 7200, "8000 / 1.1 rounded down to a step");
  for (const bad of [0.9, 1.6, NaN]) assert.equal(planWith(here, "UNCONSTRAINED", {}, { setpointOvershoot: bad }).status, "INVALID", String(bad));
});

test("a bad profile name or a profile that leaves the parameters inconsistent is INVALID, and every decision stays read only", () => {
  const bad = planGentle({ ...base, policy: { actuatorProfile: "SOMETHING" as unknown as ActuatorProfileId } });
  assert.equal(bad.status, "INVALID");
  assert.match(bad.reasons.join(" "), /actuatorProfile/);
  const clash = planGentle({ ...base, params: { minW: 100, hardMaxW: 300 }, policy: { actuatorProfile: "TOU_SLOT_EDITOR" } });
  assert.equal(clash.status, "INVALID");
  assert.match(clash.reasons.join(" "), /actuator profile TOU_SLOT_EDITOR/);
  for (const id of Object.keys(GENTLE_ACTUATOR_PROFILES) as ActuatorProfileId[]) {
    const d = planWith(here, id);
    assert.equal(d.actuationSupported, false);
    assert.equal(d.actuator.automaticApplyAuthorised, false);
    assert.equal(d.label, CONTROLLER_LABEL);
    assert.equal(d.guarantee, "NONE");
  }
});

// ---- mutants of the new constraints: a probe that passes on the real source and must FAIL on each one ---------------------------------------------

const SRC_PATH = new URL("../src/gentleController.ts", import.meta.url);
const SRC = readFileSync(SRC_PATH, "utf8");

/** Each entry is true when the constraint holds in `m`. */
function probe(m: Mod): Record<string, boolean> {
  const P = { ...m.DEFAULT_GENTLE_PARAMS };
  const out: Record<string, boolean> = {};
  const held = planWith(m, "TOU_SLOT_EDITOR", { socPct: 50, elapsedMin: 40, currentSetpointW: planWith(m, "UNCONSTRAINED").setpointW, lastChangeElapsedMin: 0 });
  out.dwell = held.codes.includes("HELD_DWELL");
  const free = planWith(m, "FREE_POWER_LEASE");
  const cut = planWith(m, "FREE_POWER_LEASE", { currentSetpointW: free.setpointW, lastChangeElapsedMin: 0, elapsedMin: 30, socPct: 25, ceilings: [m.maxChargePowerCeiling(8000, (free.setpointW as number) - 1000)] });
  out.budget = free.changesLeft === 0 && m.applyActuatorProfile(P, "FREE_POWER_LEASE").params.maxChanges === 0;
  out.fixedFlag = cut.actuator.applicableNow === false && cut.stopRecommended === true;
  out.range = m.applyActuatorProfile({ ...P, hardMaxW: 9000 }, "TOU_SLOT_EDITOR").params.hardMaxW === 8000;
  out.step = m.applyActuatorProfile({ ...P, stepW: 150 }, "TOU_SLOT_EDITOR").params.stepW === 200;
  out.basisMin = m.maxChargePowerCeiling(8000, 5000).watts === 5000;
  const dc = { name: "battery_limit", watts: 8000, basis: "BATTERY_DC" as const };
  out.overshoot = m.planGentle({ ...base, ceilings: [dc], targetSocPct: 100, socPct: 5, params: { setpointOvershoot: 1.1 } }).ceilingW === 7200;
  const dflt = m.planGentle({ ...base, bufferMin: undefined });
  out.defaultBuffer = dflt.deadlineInMin === 300;
  return out;
}

const MUTANTS: Array<{ id: string; from: string; to: string; killedBy: string }> = [
  { id: "dwell not raised to the path's minimum", from: 'set("dwellMin", Math.max(p.dwellMin, a.minDwellMin));', to: 'set("dwellMin", p.dwellMin);', killedBy: "dwell" },
  { id: "budget not cut to the path's adjustments", from: 'set("maxChanges", Math.min(p.maxChanges, a.maxAdjustmentsPerWindow));', to: 'set("maxChanges", p.maxChanges);', killedBy: "budget" },
  { id: "range not cut to the path's maximum", from: 'set("hardMaxW", Math.min(p.hardMaxW, a.maxW));', to: 'set("hardMaxW", p.hardMaxW);', killedBy: "range" },
  { id: "step granularity ignored", from: "if (p.stepW % a.stepW !== 0) set(", to: "if (false) set(", killedBy: "step" },
  { id: "fixed-rate change treated as applicable", from: 'const fixed = c.change !== "START" && !out.actuator.midWindowAdjustment;', to: "const fixed = false;", killedBy: "fixedFlag" },
  { id: "maximum is the larger of the two limits", from: "Math.min(firmwareBoundW as number, operatingLimitW as number)", to: "Math.max(firmwareBoundW as number, operatingLimitW as number)", killedBy: "basisMin" },
  { id: "overshoot ignored for a battery-side limit", from: 'if (c.basis === "BATTERY_DC") return w / overshoot;', to: 'if (c.basis === "BATTERY_DC") return w;', killedBy: "overshoot" },
  { id: "missing buffer is zero, not 60", from: "const bufferMin = input.bufferMin === undefined ? GENTLE_DEFAULT_BUFFER_MIN : input.bufferMin;", to: "const bufferMin = input.bufferMin === undefined ? 0 : input.bufferMin;", killedBy: "defaultBuffer" },
];

test("the probe passes on the real source (so a failing probe means a killed mutant, not a broken probe)", () => {
  assert.deepEqual(Object.values(probe(here)).filter((v) => !v), []);
});

for (const mu of MUTANTS) {
  test("mutant: " + mu.id, async () => {
    assert.equal(SRC.split(mu.from).length, 2, "the mutation anchor occurs exactly once");
    const dir = mkdtempSync(join(tmpdir(), "gentle-mut-"));
    try {
      const time = new URL("../src/time.ts", import.meta.url).href;
      const settings = new URL("../src/settings.ts", import.meta.url).href;
      const mutated = SRC.replace(mu.from, mu.to).replace('from "./time.ts"', 'from "' + time + '"').replace('from "./time.ts"', 'from "' + time + '"').replace('from "./settings.ts"', 'from "' + settings + '"');
      const file = join(dir, "gentleController.mut.ts");
      writeFileSync(file, mutated, "utf8");
      const m = (await import(pathToFileURL(file).href)) as Mod;
      const r = probe(m);
      assert.equal(r[mu.killedBy], false, "the probe '" + mu.killedBy + "' must fail on this mutant: " + JSON.stringify(r));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
}
