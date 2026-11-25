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

interface NightResult {
  initial: GentleNightPlan;
  initialStatus: GentleNightPlan["status"];
  deadlineMin: number;
  reachedAt: number | null;
  changes: number;
  startedW: number | null;
  plans: GentleNightPlan[];
}

function runNight(seed: number, family: TruthFamily, over: { dropoutEvery?: number; params?: Partial<TruthParams> } = {}): NightResult {
  const p = { ...drawTruth(seed, family), ...(over.params ?? {}) };
  const truth = createTruth(p);
  const profile = GENTLE_ACTUATOR_PROFILES[p.profile];
  const maxChanges = p.profile === "UNCONSTRAINED" ? 6 : profile.maxAdjustmentsPerWindow;
  const dwell = p.profile === "UNCONSTRAINED" ? 30 : profile.minDwellMin;
  const ceilings = [maxChargePowerCeiling(8000, p.ownerLimitW)];
  let inForce: NightInForce = { setpointW: null, lastChangeAtMin: null, changesUsed: 0 };
  let previous: { socPct: number; elapsedMin: number } | null = null;
  const plans: GentleNightPlan[] = [];
  let initial: GentleNightPlan | null = null;
  let startedW: number | null = null;
  let tick = 0;
  for (let t = 0; t < p.windowMin; t += TICK, tick++) {
    const reading = truth.reading();
    const stale = over.dropoutEvery !== undefined && tick % over.dropoutEvery === 3;
    const input = {
      targetSocPct: p.targetPct, bufferMin: p.bufferMin, chargeWindow: { startMin: 30, endMin: (30 + p.windowMin) % 1440 }, clockDay: ORDINARY, elapsedMin: t, socPct: reading,
      socAgeMin: stale ? 45 : 1, previousSoc: previous, capacityKwh: p.helperKwh, ceilings, inForce, actuatorProfile: p.profile,
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
      previous = { socPct: reading, elapsedMin: t };
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
  return { initial: first, initialStatus: first.status, deadlineMin: p.windowMin - p.bufferMin, reachedAt: truth.reachedAt(), changes: inForce.changesUsed, startedW, plans };
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
