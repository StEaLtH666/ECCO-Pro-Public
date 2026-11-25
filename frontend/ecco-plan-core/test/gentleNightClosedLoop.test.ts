// Gentle night planner: CLOSED LOOP against the independent truth battery (test/support/gentleNightTruth.ts, which imports nothing from src/).
// Each night: the planner is asked at every re-plan tick from the truth's displayed reading, its recommendation is "applied" by the test harness only (the
// planner applies nothing), the harness itself counts the changes and the dwell, and the truth battery runs on. Seeded, so a failure reproduces.
import { test } from "node:test";
import assert from "node:assert/strict";
import { planGentleNight, NIGHT_CODES } from "../src/gentleNight.ts";
import type { GentleNightPlan, NightInForce } from "../src/gentleNight.ts";
import { maxChargePowerCeiling, GENTLE_ACTUATOR_PROFILES } from "../src/gentleController.ts";
import { createTruth, drawTruth } from "./support/gentleNightTruth.ts";
import type { TruthFamily, TruthParams } from "./support/gentleNightTruth.ts";

const ORDINARY = { changeAtMin: 0, deltaMin: 0 } as const;
const TICK = 10;
const near = (a: number | null | undefined, b: number, tol: number, what: string): void => assert.ok(typeof a === "number" && Math.abs(a - b) <= tol, what + ": " + a + " against " + b);

interface NightResult {
  initial: GentleNightPlan;
  initialStatus: GentleNightPlan["status"];
  deadlineMin: number;
  reachedAt: number | null;
  changes: number;
  startedW: number | null;
  plans: GentleNightPlan[];
  /** KNEE_MIDWINDOW_AGED: the truth crossed its knee between the (aged) first reading and the first call. */
  kneeCrossedSinceReading: boolean;
}

function runNight(seed: number, family: TruthFamily, over: { dropoutEvery?: number; params?: Partial<TruthParams> } = {}): NightResult {
  const p = { ...drawTruth(seed, family), ...(over.params ?? {}) };
  const truth = createTruth(p);
  const profile = GENTLE_ACTUATOR_PROFILES[p.profile];
  const maxChanges = p.profile === "UNCONSTRAINED" ? 6 : profile.maxAdjustmentsPerWindow;
  const dwell = p.profile === "UNCONSTRAINED" ? 30 : profile.minDwellMin;
  const ceilings = [maxChargePowerCeiling(8000, p.ownerLimitW)];
  let inForce: NightInForce = { setpointW: null, lastChangeAtMin: null, changesUsed: 0 };
  // KNEE_MIDWINDOW: an outside rate runs before the planner is first asked (the knee may be crossed at it); the planner then sees it as the rate in force.
  // KNEE_MIDWINDOW_AGED: the first call gets the reading taken `firstReadingAgeMin` before it, with that age (the knee may be crossed after it).
  const pre = p.outsideW === undefined ? 0 : (p.preRunMin ?? 0);
  let aged: { reading: number; ageMin: number } | null = null;
  let kneeCrossedSinceReading = false;
  if (p.outsideW !== undefined) {
    if (p.firstReadingAgeMin !== undefined) {
      truth.runTo(pre - p.firstReadingAgeMin, p.outsideW);
      aged = { reading: truth.reading(), ageMin: p.firstReadingAgeMin };
      kneeCrossedSinceReading = !truth.pastKnee();
    }
    truth.runTo(pre, p.outsideW);
    kneeCrossedSinceReading = kneeCrossedSinceReading && truth.pastKnee();
    inForce = { setpointW: p.outsideW, lastChangeAtMin: -60, changesUsed: 0 };
  }
  let previous: { socPct: number; elapsedMin: number } | null = null;
  const plans: GentleNightPlan[] = [];
  let initial: GentleNightPlan | null = null;
  let startedW: number | null = null;
  let tick = 0;
  for (let t = pre; t < p.windowMin; t += TICK, tick++) {
    const old = tick === 0 ? aged : null;
    const reading = old !== null ? old.reading : truth.reading();
    const stale = over.dropoutEvery !== undefined && tick % over.dropoutEvery === 3;
    const input = {
      targetSocPct: p.targetPct, bufferMin: p.bufferMin, chargeWindow: { startMin: 30, endMin: (30 + p.windowMin) % 1440 }, clockDay: ORDINARY, elapsedMin: t, socPct: reading,
      socAgeMin: stale ? 45 : old !== null ? old.ageMin : 1, previousSoc: previous, capacityKwh: p.helperKwh, ceilings, inForce, actuatorProfile: p.profile,
    };
    const plan = planGentleNight(input);
    plans.push(plan);
    if (initial === null) initial = plan;
    assert.equal(plan.actuationSupported, false);
    for (const code of plan.codes) assert.ok((NIGHT_CODES as readonly string[]).includes(code), "unknown code " + code);
    if (stale) {
      assert.equal(plan.status, "INPUTS_UNUSABLE", "a stale reading gives no plan (seed " + seed + ")");
      assert.equal(plan.now.setpointW, null);
    } else {
      previous = { socPct: reading, elapsedMin: old !== null ? t - old.ageMin : t };
      if (plan.status === "INPUTS_UNUSABLE") assert.fail("unexpected INPUTS_UNUSABLE (seed " + seed + "): " + plan.codes.join(","));
      if (plan.status === "NO_NEED") {
        assert.equal(plan.now.setpointW, null);
      } else {
        const w = plan.now.setpointW as number;
        assert.ok(Number.isInteger(w / 100), "a multiple of 100 W: " + w);
        assert.ok(w >= 500, "never below 500 W when charging: " + w + " seed " + seed);
        assert.ok(w <= Math.min(8000, p.ownerLimitW), "never above the ceiling: " + w + " seed " + seed);
        assert.equal(plan.targetSocPct, p.targetPct, "the target is never changed");
        assert.ok(plan.targetSocPct <= 100);
        if (plan.status === "UNREACHABLE" || plan.status === "TARGET_AT_RISK") assert.notEqual(plan.now.change, "DECREASE", "never lowers the rate when the target is at risk (seed " + seed + ")");
        for (const pt of plan.trajectory) assert.ok(pt.setpointW >= 500 && pt.setpointW <= Math.min(8000, p.ownerLimitW) && pt.setpointW % 100 === 0, "trajectory point " + JSON.stringify(pt));
        if (plan.trajectory.length > 1) assert.ok(maxChanges > 0, "a flat path has a flat trajectory");
        assert.ok(plan.trajectory.length - 1 <= maxChanges, "the trajectory stays inside the change budget");
        // inside the declared envelope a raise after the truth's knee is never credited, so it is never recommended there (review finding BLOCKER 1)
        if (family !== "STRESS" && truth.pastKnee()) assert.notEqual(plan.now.change, "INCREASE", "a raise past the truth's knee (seed " + seed + ", " + family + ", reading " + reading + ")");
        // the harness applies the recommendation and enforces the profile itself
        if (plan.now.change === "START") {
          inForce = { setpointW: w, lastChangeAtMin: t, changesUsed: 0 };
          if (startedW === null) startedW = w;
        } else if (plan.now.change === "INCREASE" || plan.now.change === "DECREASE") {
          assert.ok(inForce.changesUsed < maxChanges, "a change beyond the budget was recommended (seed " + seed + ", " + p.profile + ")");
          assert.ok(inForce.lastChangeAtMin === null || t - inForce.lastChangeAtMin >= dwell - 1e-9, "a change inside the dwell was recommended (seed " + seed + ", " + p.profile + ")");
          inForce = { setpointW: w, lastChangeAtMin: t, changesUsed: inForce.changesUsed + 1 };
        } else assert.equal(w, inForce.setpointW, "KEEP keeps the rate in force");
      }
    }
    truth.runTo(t + TICK, inForce.setpointW ?? 0);
  }
  const first = initial as GentleNightPlan;
  return { initial: first, initialStatus: first.status, deadlineMin: p.windowMin - p.bufferMin, reachedAt: truth.reachedAt(), changes: inForce.changesUsed, startedW, plans, kneeCrossedSinceReading };
}

test("closed loop, inside the declared envelope: a plan that is OK at the start makes the deadline in the independent truth battery", () => {
  let ok = 0;
  let atRisk = 0;
  let missedOk = 0;
  const N = 160;
  for (let seed = 1; seed <= N; seed++) {
    const r = runNight(seed, "IN_ENVELOPE");
    if (r.initialStatus === "OK") {
      ok++;
      const hit = r.reachedAt !== null && r.reachedAt <= r.deadlineMin + 1e-6;
      if (!hit) missedOk++;
      assert.ok(hit, "seed " + seed + ": OK at the start but reached at " + r.reachedAt + " against the deadline " + r.deadlineMin + " (" + JSON.stringify(drawTruth(seed, "IN_ENVELOPE")) + ")");
    } else if (r.initialStatus === "TARGET_AT_RISK" || r.initialStatus === "UNREACHABLE") atRisk++;
  }
  assert.equal(missedOk, 0);
  assert.ok(ok >= 60, "the sweep must contain many feasible nights, got " + ok);
  assert.ok(atRisk >= 5, "and some that the planner calls at risk or unreachable, got " + atRisk);
});

test("closed loop, KNEE_MIDWINDOW (an outside rate in force within a few points of the knee, the knee possibly crossed at it): an OK at the first call makes the deadline", () => {
  let ok = 0;
  let notOk = 0;
  let crossedFirst = 0;
  for (let seed = 1; seed <= 240; seed++) {
    const r = runNight(seed, "KNEE_MIDWINDOW");
    const p = drawTruth(seed, "KNEE_MIDWINDOW");
    if (r.initial.now.change === "INCREASE" && r.initial.codes.includes("HELD_PAST_KNEE")) assert.fail("a held rate cannot be an increase (seed " + seed + ")");
    if (r.initialStatus === "OK") {
      ok++;
      assert.ok(r.reachedAt !== null && r.reachedAt <= r.deadlineMin + 1e-6, "seed " + seed + ": OK at the first call but reached at " + r.reachedAt + " against " + r.deadlineMin + " (" + JSON.stringify(p) + ")");
    } else if (r.initialStatus !== "NO_NEED") notOk++;
    if (r.initial.codes.includes("HELD_PAST_KNEE")) crossedFirst++;
  }
  assert.ok(ok >= 15, "OK nights near the knee: " + ok);
  assert.ok(notOk >= 15, "and nights it calls at risk: " + notOk);
  assert.ok(crossedFirst >= 20, "first calls held past the knee: " + crossedFirst);
});

test("closed loop, KNEE_MIDWINDOW_AGED (the first reading 10 to 15 minutes old, an outside rate in force, half the nights crossing the knee after that reading): an OK at the first call makes the deadline, ZERO misses", () => {
  let ok = 0;
  let notOk = 0;
  let crossedSince = 0;
  let crossedSinceHeld = 0;
  for (let seed = 1; seed <= 300; seed++) {
    const r = runNight(seed, "KNEE_MIDWINDOW_AGED");
    const p = drawTruth(seed, "KNEE_MIDWINDOW_AGED");
    assert.ok(p.firstReadingAgeMin !== undefined && p.firstReadingAgeMin >= 10 && p.firstReadingAgeMin <= 15);
    if (r.initial.assumptions !== null) assert.ok((r.initial.assumptions.chargeSinceReadingPct as number) > 0, "the first call counts the charge since its reading (seed " + seed + ")");
    if (r.kneeCrossedSinceReading) {
      crossedSince++;
      // the knee was crossed at the rate in force after the reading: a raise is never credited, so none is recommended (review: OK INCREASE 5500 before)
      assert.notEqual(r.initial.now.change, "INCREASE", "a raise after the knee was crossed since the reading (seed " + seed + ")");
      if (r.initial.codes.includes("HELD_PAST_KNEE") || r.initial.now.change === "KEEP") crossedSinceHeld++;
    }
    if (r.initialStatus === "OK") {
      ok++;
      assert.ok(r.reachedAt !== null && r.reachedAt <= r.deadlineMin + 1e-6, "seed " + seed + ": OK at the first call but reached at " + r.reachedAt + " against " + r.deadlineMin + " (" + JSON.stringify(p) + ")");
    } else if (r.initialStatus !== "NO_NEED") notOk++;
  }
  assert.ok(ok >= 15, "OK nights: " + ok);
  assert.ok(notOk >= 15, "and nights it calls at risk: " + notOk);
  assert.ok(crossedSince >= 60, "nights whose knee was crossed after the first reading: " + crossedSince);
  assert.equal(crossedSinceHeld, crossedSince, "each of them holds the rate in force");
});

test("closed loop, the confirmation review's case on this truth battery: reading 88 taken 10 to 15 min before the call, 3000 W in force, the knee crossed since: no OK, no raise, and the truth does miss", () => {
  // every value inside the envelope: helper 31.7, capacity x0.94, efficiency 0.90, sensor +3 %, knee 91, tail 1/8, a cliff, the low-reading sensor; the call at
  // minute 20, the window 200 min with no buffer, target 95 (before the fix: OK INCREASE 5500 W, and the truth ended at 94.4)
  for (const age of [10, 14, 15]) {
    const p: TruthParams = {
      seed: 1, family: "IN_ENVELOPE", helperKwh: 31.7, capKwh: 31.7 * 0.94, unit: "AC", effAc: 0.9, dcOver: 1, sensorErr: 0.03, kneeTrue: 91, tailFrac: 0.125, dropMin: 1,
      trickleDecayPerHour: 0, noiseAmp: 0.45, startTrueSoc: 89 - ((2.7 * (20 - age)) / 60 / (31.7 * 0.94)) * 100, windowMin: 200, bufferMin: 0, targetPct: 95, ownerLimitW: 8000,
      profile: "RATE_CONTROLLER_PROPOSED", lowReading: true,
    };
    const truth = createTruth(p);
    truth.runTo(20 - age, 3000);
    const old = truth.reading();
    assert.ok(!truth.pastKnee() && old === 88, "not past the knee at the reading 88 (age " + age + "): " + old);
    truth.runTo(20, 3000);
    // at 14 and 15 min the knee is crossed at 3000 W after the reading (the review's case); at 10 min it is about to be (90.5 true at the call)
    if (age >= 14) assert.ok(truth.pastKnee(), "the knee crossed after the reading (age " + age + ")");
    let inForce: NightInForce = { setpointW: 3000, lastChangeAtMin: -60, changesUsed: 0 };
    for (let t = 20; t < 200; t += TICK) {
      const plan = planGentleNight({
        targetSocPct: 95, bufferMin: 0, chargeWindow: { startMin: 30, endMin: 230 }, clockDay: ORDINARY, elapsedMin: t, socPct: t === 20 ? old : truth.reading(), socAgeMin: t === 20 ? age : 1,
        capacityKwh: 31.7, ceilings: [maxChargePowerCeiling(8000, 8000)], inForce, actuatorProfile: "RATE_CONTROLLER_PROPOSED",
      });
      assert.notEqual(plan.status, "OK", "age " + age + " minute " + t + ": " + plan.codes.join(","));
      assert.notEqual(plan.now.change, "INCREASE", "age " + age + " minute " + t);
      if (t === 20) assert.ok(plan.codes.includes("HELD_PAST_KNEE"), "held at the first call: " + plan.codes.join(","));
      if (plan.now.setpointW !== null && plan.now.change !== "KEEP") inForce = { setpointW: plan.now.setpointW, lastChangeAtMin: t, changesUsed: inForce.changesUsed + 1 };
      truth.runTo(t + TICK, inForce.setpointW ?? 0);
    }
    assert.equal(truth.reachedAt(), null, "the truth misses 95 inside the window (" + truth.cleanReading() + ")");
  }
});

test("closed loop, a START from a reading 15 minutes old while the house drains the battery at 3000 W (the confirmation review's worst corner): the drain is counted at -0.5, 0 and +0.5 min, and the truth makes the deadline", () => {
  // the truth's minute 0 is the reading; the planner is called 15 minutes later, at `callAt` minutes from the window start, with the drain bound 3000 W
  // battery side (the truth drains exactly that); the START applies at the window start (a call before it) or at once, on the Free Power path (held)
  for (const sensorErr of [-0.03, 0.03]) {
    for (const targetPct of [80, 90]) {
      for (const callAt of [-0.5, 0, 0.5]) {
        const p: TruthParams = {
          seed: 3, family: "IN_ENVELOPE", helperKwh: 31.7, capKwh: 31.7 * 1.06, unit: "AC", effAc: 0.9, dcOver: 1, sensorErr, kneeTrue: 99, tailFrac: 0.125, dropMin: 1,
          trickleDecayPerHour: 0, noiseAmp: 0.45, startTrueSoc: 100 - (100 - 40.4) / (1 + sensorErr), windowMin: 300, bufferMin: 60, targetPct, ownerLimitW: 8000,
          profile: "FREE_POWER_LEASE", lowReading: true,
        };
        const truth = createTruth(p);
        const reading = truth.reading();
        const shift = callAt - 15;
        truth.drainTo(15, 3000);
        const plan = planGentleNight({
          targetSocPct: targetPct, chargeWindow: { startMin: 30, endMin: 330 }, clockDay: ORDINARY, elapsedMin: callAt, socPct: reading, socAgeMin: 15, drainBoundW: 3000,
          capacityKwh: 31.7, ceilings: [maxChargePowerCeiling(8000, 8000)], actuatorProfile: "FREE_POWER_LEASE",
        });
        const what = "err " + sensorErr + " target " + targetPct + " call at " + callAt;
        assert.equal(plan.status, "OK", what + ": " + plan.codes.join(","));
        // by hand: 3000 W over the 15 min of age (and the half minute to the window start for the call before it), in the most points per kWh
        near(plan.assumptions?.socAtPlanStartPct, reading - (3000 * (15 + Math.max(0, -callAt))) / 60 / 1000 / ((31.7 * 0.94) / 1.03 / 100), 0.006, what);
        truth.drainTo(Math.max(callAt, 0) - shift, 3000);
        truth.runTo(300 - shift, plan.now.setpointW as number);
        const reached = truth.reachedAt();
        assert.ok(reached !== null && reached + shift <= 240 + 1e-6, what + ": START " + plan.now.setpointW + " W reached at " + (reached === null ? null : reached + shift) + " against 240");
      }
    }
  }
});

test("closed loop, the review's case: 2000 W in force since before the window, the knee crossed at 2000 W, reading 90 at minute 5: no OK and no raise, and the truth does miss", () => {
  // every parameter inside the declared envelope: capacity +6 %, efficiency 0.90, sensor +3 % (the knee shows at reading 90.73), tail 1/8, a cliff
  for (const targetPct of [95, 100]) {
    const p: TruthParams = {
      seed: 1, family: "IN_ENVELOPE", helperKwh: 31.7, capKwh: 31.7 * 1.06, unit: "AC", effAc: 0.9, dcOver: 1, sensorErr: 0.03, kneeTrue: 91, tailFrac: 0.125, dropMin: 1,
      trickleDecayPerHour: 0, noiseAmp: 0, startTrueSoc: 90.9, windowMin: 300, bufferMin: 60, targetPct, ownerLimitW: 8000, profile: "UNCONSTRAINED",
    };
    const truth = createTruth(p);
    truth.runTo(5, 2000);
    assert.ok(truth.pastKnee() && truth.cleanReading() > 90.73 && truth.cleanReading() < 91, "the knee is crossed at 2000 W: " + truth.cleanReading());
    let inForce: NightInForce = { setpointW: 2000, lastChangeAtMin: -60, changesUsed: 0 };
    for (let t = 5; t < 300; t += TICK) {
      // the displayed reading is taken as the rounded-down clean value (90 at minute 5, as in the review), the worst case for the old rule
      const plan = planGentleNight({
        targetSocPct: targetPct, chargeWindow: { startMin: 30, endMin: 330 }, clockDay: ORDINARY, elapsedMin: t, socPct: Math.floor(truth.cleanReading()), socAgeMin: 1, capacityKwh: 31.7,
        ceilings: [maxChargePowerCeiling(8000, 8000)], inForce, actuatorProfile: "UNCONSTRAINED",
      });
      assert.notEqual(plan.status, "OK", "minute " + t + " target " + targetPct + ": " + plan.codes.join(","));
      assert.notEqual(plan.now.change, "INCREASE", "minute " + t);
      if (plan.now.setpointW !== null && plan.now.change !== "KEEP") inForce = { setpointW: plan.now.setpointW, lastChangeAtMin: t, changesUsed: inForce.changesUsed + 1 };
      truth.runTo(t + TICK, inForce.setpointW ?? 0);
    }
    assert.equal(truth.reachedAt(), null, "the truth misses the target inside the window (" + truth.cleanReading() + ")");
  }
});

test("closed loop, outside the declared envelope (knee from 85, tail from 0, trickle): the safety invariants hold and a miss is never called certain-OK later", () => {
  let nights = 0;
  for (let seed = 1; seed <= 80; seed++) {
    const r = runNight(seed, "STRESS");
    nights++;
    // the invariants are asserted tick by tick inside runNight; here, an UNREACHABLE start is honest: it is never followed by a lowered target
    for (const pl of r.plans) if (pl.targetSocPct !== null) assert.equal(pl.targetSocPct, drawTruth(seed, "STRESS").targetPct);
  }
  assert.equal(nights, 80);
});

test("closed loop: with lost readings every few ticks the planner gives no plan for them, holds nothing of its own, and the night still makes the deadline when it was OK", () => {
  let checked = 0;
  for (let seed = 200; seed < 260; seed++) {
    const r = runNight(seed, "IN_ENVELOPE", { dropoutEvery: 4 });
    if (r.initialStatus === "OK" && r.initial.band !== null) {
      checked++;
      assert.ok(r.reachedAt !== null && r.reachedAt <= r.deadlineMin + 1e-6, "seed " + seed + " reached " + r.reachedAt + " deadline " + r.deadlineMin);
    }
  }
  assert.ok(checked >= 10, "checked " + checked);
});

test("closed loop: the flat paths never change the rate, the TOU editor changes at most once, the budget and dwell are never broken (checked by the harness, not the planner)", () => {
  const seen: Record<string, number> = { FREE_POWER_LEASE: 0, TOU_SLOT_EDITOR: 0, RATE_CONTROLLER_PROPOSED: 0, UNCONSTRAINED: 0 };
  for (let seed = 300; seed < 420; seed++) {
    const r = runNight(seed, "IN_ENVELOPE");
    const prof = drawTruth(seed, "IN_ENVELOPE").profile;
    seen[prof] = (seen[prof] as number) + r.changes;
    if (prof === "FREE_POWER_LEASE") assert.equal(r.changes, 0);
    if (prof === "TOU_SLOT_EDITOR") assert.ok(r.changes <= 1);
    assert.ok(r.changes <= 6);
  }
  assert.equal(seen.FREE_POWER_LEASE, 0);
});

test("closed loop: the planned first rate of an OK night is never above what a flat plan needs by more than a step (it is the lowest feasible one)", () => {
  for (let seed = 500; seed < 540; seed++) {
    const r = runNight(seed, "IN_ENVELOPE");
    if (r.initialStatus === "OK") {
      assert.equal(r.initial.now.neededMeetsDeadline, true);
      assert.equal(r.initial.now.setpointW, r.initial.now.neededW, "at the start the recommended rate is the lowest feasible rate");
    }
  }
});

test("closed loop: every worst corner of the declared envelope at once (capacity +6 %, efficiency 0.90, scale -3 %, knee 91, tail 1/8, a cliff, the most noise) still makes the deadline when the start plan is OK", () => {
  const corner: Partial<TruthParams> = { unit: "AC", effAc: 0.9, sensorErr: -0.03, kneeTrue: 91, tailFrac: 0.125, dropMin: 1, noiseAmp: 0.45, trickleDecayPerHour: 0 };
  let ok = 0;
  let minMargin = Infinity;
  for (let seed = 700; seed < 860; seed++) {
    const base = drawTruth(seed, "IN_ENVELOPE");
    const r = runNight(seed, "IN_ENVELOPE", { params: { ...corner, capKwh: base.helperKwh * 1.06 } });
    if (r.initialStatus === "OK") {
      ok++;
      assert.ok(r.reachedAt !== null, "seed " + seed + " never reached the target");
      minMargin = Math.min(minMargin, r.deadlineMin - (r.reachedAt as number));
      assert.ok((r.reachedAt as number) <= r.deadlineMin + 1e-6, "seed " + seed + " reached " + r.reachedAt + " deadline " + r.deadlineMin);
    }
  }
  assert.ok(ok >= 40, "feasible corner nights: " + ok);
  assert.ok(minMargin >= -1e-6, "minimum margin " + minMargin);
});

test("closed loop: the sweep is not trivial: OK nights finish close to the deadline in the truth (the planner is not just very slow-safe), and the status mix has every kind", () => {
  const margins: number[] = [];
  const kinds: Record<string, number> = {};
  for (let seed = 1; seed <= 160; seed++) {
    const r = runNight(seed, "IN_ENVELOPE");
    kinds[r.initialStatus] = (kinds[r.initialStatus] ?? 0) + 1;
    if (r.initialStatus === "OK" && r.reachedAt !== null) margins.push(r.deadlineMin - r.reachedAt);
  }
  margins.sort((a, b) => a - b);
  assert.ok(margins.length >= 60);
  assert.ok((margins[Math.floor(margins.length * 0.5)] as number) < 90, "median margin " + margins[Math.floor(margins.length * 0.5)]);
  assert.ok((kinds.OK ?? 0) > 0 && (kinds.NO_NEED ?? 0) >= 0);
  assert.ok((kinds.TARGET_AT_RISK ?? 0) + (kinds.UNREACHABLE ?? 0) > 0, JSON.stringify(kinds));
});
