// Gentle night planner (src/gentleNight.ts): the safety properties an independent review found untested or wrong (BLOCKER 1 to 3, MAJOR 4 to 7), each
// pinned by a behavioural assertion with a value worked out BY HAND from the stated model (not copied from the code). READ ONLY: a pure function.
// The model numbers used below: pessimistic kWh per point = 31.7 x 1.06 / 0.97 / 100 = 0.346412, efficiency 0.90, start = reading - 1.0 (resolution 1,
// noise 0.5), knee 90, tail 1/8 after a one minute cliff; optimistic kWh per point = 31.7 x 0.94 / 1.03 / 100 = 0.289301, efficiency 0.97, start + 0.5.
import { test } from "node:test";
import assert from "node:assert/strict";
import { planGentleNight, windowFromSlotTable, NIGHT_CODES } from "../src/gentleNight.ts";
import type { GentleNightInput, GentleNightPlan } from "../src/gentleNight.ts";
import { GENTLE_ACTUATOR_PROFILES, maxChargePowerCeiling } from "../src/gentleController.ts";
import { rng, slot } from "./fixtures.ts";

const ORD = { changeAtMin: 0, deltaMin: 0 } as const;
const base: GentleNightInput = {
  targetSocPct: 80, chargeWindow: { startMin: 30, endMin: 330 }, clockDay: ORD, elapsedMin: 0, socPct: 20, socAgeMin: 1, capacityKwh: 31.7, ceilings: [maxChargePowerCeiling(8000, 8000)],
};
const plan = (over: Partial<GentleNightInput> = {}): GentleNightPlan => planGentleNight({ ...base, ...over });
const gen = (over: Partial<GentleNightInput> = {}): GentleNightPlan => plan({ actuatorProfile: "UNCONSTRAINED", ...over });
const PK = (31.7 * 1.06) / 0.97 / 100;
const near = (a: number | null | undefined, b: number, tol: number, what: string): void => assert.ok(typeof a === "number" && Math.abs(a - b) <= tol, what + ": " + a + " against " + b);
const band = (p: GentleNightPlan) => p.band as NonNullable<GentleNightPlan["band"]>;

test("BLOCKER 1: the knee is decided from the reading's optimistic estimate: from reading 89 (89 + 0.5 + 0.5 = the knee 90) a rate in force is held and a raise is never credited", () => {
  const inForce = { setpointW: 2000, lastChangeAtMin: -60, changesUsed: 0 };
  for (const socPct of [89, 90, 91, 93]) {
    for (const targetSocPct of [95, 100]) {
      const p = gen({ elapsedMin: 5, socPct, targetSocPct, inForce });
      const what = "reading " + socPct + " target " + targetSocPct;
      assert.equal(p.now.change, "KEEP", what);
      assert.equal(p.now.setpointW, 2000, what);
      assert.ok(p.codes.includes("HELD_PAST_KNEE"), what);
      assert.notEqual(p.status, "OK", what);
      // the tail is anchored at the lower of the rate in force and the rate tried: no rate makes the deadline (0.125 x 2000 x 0.9 = 225 W at most)
      assert.equal(p.now.neededMeetsDeadline, false, what);
      assert.equal(p.now.neededW, 8000, what);
      assert.ok(p.codes.includes("RATE_AT_CEILING"), what);
    }
  }
  // by hand, reading 90: the pessimistic world starts ON THE TAIL at 89 with 225 W for 235 min: 0.88125 kWh = 2.544 points, so 91.5 at the deadline
  near(band(gen({ elapsedMin: 5, socPct: 90, targetSocPct: 95, inForce })).pessimisticHeld.socAtDeadlinePct, 91.5, 0.05, "SOC at the deadline");
  // just below the threshold (88.9 + 1.0 < 90) the knee is surely ahead: the raise is credited and made (the threshold is inclusive, not a margin)
  const below = gen({ elapsedMin: 5, socPct: 88.9, targetSocPct: 95, inForce });
  assert.equal(below.now.change, "INCREASE");
  assert.ok(!below.codes.includes("HELD_PAST_KNEE"));
  // a target at or below the pessimistic knee is reached on the plateau: no hold there
  assert.notEqual(gen({ elapsedMin: 5, socPct: 89.5, targetSocPct: 90, inForce }).now.change, "KEEP");
});

test("BLOCKER 1: a start past the knee is on the tail, anchored at the lower of the rate in force and the rate tried (by hand)", () => {
  // reading 93, 5200 W held: the pessimistic world starts at 92 on the tail, 0.125 x 5200 x 0.9 = 585 W: 3 points x 0.346412 = 1.03924 kWh, 106.59 min
  const held = gen({ elapsedMin: 100, socPct: 93, targetSocPct: 95, inForce: { setpointW: 5200, lastChangeAtMin: 0, changesUsed: 0 } });
  near(band(held).pessimisticHeld.finishMin, 100 + (3 * PK) / 0.585 * 60, 0.15, "pessimistic finish on the tail");
  assert.equal(held.status, "OK");
  // reading 93 with 2000 W in force: a raise to 8000 W is anchored at 2000 W, so it is not credited and no rate makes the deadline
  const raise = gen({ elapsedMin: 100, socPct: 93, targetSocPct: 95, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(raise.now.neededW, 8000);
  assert.equal(raise.now.neededMeetsDeadline, false);
  // a START past the knee (nothing in force) anchors at the start rate itself: 3 points in 140 min need 1.03924 kWh / (140/60 h) / (0.125 x 0.9) = 3959 W, so 4000 W
  const start = gen({ elapsedMin: 100, socPct: 93, targetSocPct: 95 });
  assert.equal(start.now.change, "START");
  assert.equal(start.now.setpointW, 4000);
});

test("BLOCKER 2: on a path that fixes the rate at the START, a rate in force above the ceiling gives STOP_RECOMMENDED, never a change; the band is the rate in force", () => {
  const p = plan({ elapsedMin: 60, socPct: 40, actuatorProfile: "FREE_POWER_LEASE", ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(p.status, "STOP_RECOMMENDED");
  assert.equal(p.stopRecommended, true);
  assert.equal(p.now.change, "STOP");
  assert.equal(p.now.setpointW, null);
  assert.deepEqual(p.trajectory, []);
  assert.ok(p.codes.includes("FORCED_BELOW_CEILING") && p.codes.includes("ACTUATOR_FIXED_RATE"));
  assert.match(p.needed.join(" "), /Stop the charge/);
  // by hand, the 8000 W that stays in force: 41 points x 0.346412 = 14.2029 kWh at 7.2 kW = 118.36 min, from minute 60
  near(band(p).pessimisticHeld.finishMin, 60 + ((41 * PK) / 7.2) * 60, 0.1, "the band is for the rate in force");
  // a path that can change still forces the rate down to the ceiling (the owner confirms it on the editor)
  const tou = plan({ elapsedMin: 60, socPct: 40, actuatorProfile: "TOU_SLOT_EDITOR", ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 1 } });
  assert.equal(tou.now.change, "DECREASE");
  assert.equal(tou.now.setpointW, 6000);
  assert.equal(tou.stopRecommended, false);
  // a sweep: after the START a fixed path only ever says KEEP or STOP, and a STOP is never OK
  const r = rng(91);
  for (let i = 0; i < 300; i++) {
    const limit = [8000, 6000, 3000][Math.floor(r() * 3)] as number;
    const q = plan({
      actuatorProfile: "FREE_POWER_LEASE", elapsedMin: Math.floor(r() * 290), socPct: Math.floor(r() * 99), targetSocPct: 50 + Math.floor(r() * 51), ceilings: [maxChargePowerCeiling(8000, limit)],
      inForce: { setpointW: 500 + 100 * Math.floor(r() * 76), lastChangeAtMin: 0, changesUsed: 0 },
    });
    if (q.now.change === "NONE") continue;
    assert.ok(q.now.change === "KEEP" || q.now.change === "STOP", q.now.change);
    if (q.now.change === "STOP") assert.equal(q.status, "STOP_RECOMMENDED");
    for (const t of q.trajectory) assert.ok(t.change === "KEEP", JSON.stringify(t));
  }
});

test("BLOCKER 3: a rate in force of 0 W is not charging (a START); one above 0 W below the minimum or off the step is refused; a negative or non-number one is invalid", () => {
  const none = gen({ elapsedMin: 60, socPct: 40 });
  const zero = gen({ elapsedMin: 60, socPct: 40, inForce: { setpointW: 0, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(zero.now.change, "START");
  assert.equal(zero.now.setpointW, none.now.setpointW);
  assert.ok(zero.codes.includes("IN_FORCE_ZERO_NOT_CHARGING") && zero.codes.includes("START"));
  // past the knee 0 W is a START too, never "KEEP 0 W", and the band is a number
  const zk = gen({ elapsedMin: 60, socPct: 92, targetSocPct: 95, inForce: { setpointW: 0, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(zk.now.change, "START");
  assert.ok((zk.now.setpointW as number) >= 500);
  for (const w of [band(zk).pessimistic, band(zk).pessimisticHeld, band(zk).expected, band(zk).optimistic]) assert.ok(Number.isFinite(w.socAtDeadlinePct), JSON.stringify(w));
  for (const w of [1, 300, 499, 2050, 7950, 3999.5]) {
    const p = gen({ elapsedMin: 60, socPct: 40, inForce: { setpointW: w, lastChangeAtMin: 0, changesUsed: 0 } });
    assert.equal(p.status, "INPUTS_UNUSABLE", String(w));
    assert.deepEqual(p.codes, ["IN_FORCE_INVALID"], String(w));
  }
  for (const w of [-100, -0.5, NaN, Infinity]) assert.deepEqual(gen({ inForce: { setpointW: w, lastChangeAtMin: 0, changesUsed: 0 } }).codes, ["INPUT_INVALID"], String(w));
  // above the ceiling (even off the step or above the firmware bound) it is never refused: it is forced down, or stopped on a fixed path
  const above = gen({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 8050, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(above.now.change, "DECREASE");
  assert.equal(above.now.setpointW, 8000);
  assert.equal(plan({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 9000, lastChangeAtMin: 0, changesUsed: 0 } }).status, "STOP_RECOMMENDED");
});

test("BLOCKER 3: with any rate in force the outputs are numbers and never below the floor (seeded sweep, every path)", () => {
  const r = rng(4242);
  const profiles = ["UNCONSTRAINED", "FREE_POWER_LEASE", "TOU_SLOT_EDITOR", "RATE_CONTROLLER_PROPOSED"] as const;
  let rated = 0;
  for (let i = 0; i < 500; i++) {
    const limit = [8000, 6000, 3000][Math.floor(r() * 3)] as number;
    const w = [0, 300, 500, 1000, 2000, 4000, 6000, 8000, 2050][Math.floor(r() * 9)] as number;
    const p = plan({
      actuatorProfile: profiles[Math.floor(r() * 4)] as (typeof profiles)[number], elapsedMin: Math.floor(r() * 300), socPct: Math.floor(r() * 1000) / 10, targetSocPct: 60 + Math.floor(r() * 41),
      ceilings: [maxChargePowerCeiling(8000, limit)], inForce: { setpointW: w, lastChangeAtMin: Math.floor(r() * 200) - 60, changesUsed: Math.floor(r() * 3) },
    });
    for (const c of p.codes) assert.ok((NIGHT_CODES as readonly string[]).includes(c), c);
    if (p.band !== null) {
      for (const o of [p.band.pessimistic, p.band.pessimisticHeld, p.band.expected, p.band.optimistic]) {
        assert.ok(Number.isFinite(o.socAtDeadlinePct) && o.socAtDeadlinePct >= 0 && o.socAtDeadlinePct <= 100, JSON.stringify(o));
        assert.ok(o.finishMin === null || Number.isFinite(o.finishMin));
      }
      assert.ok(p.marginMin === null || Number.isFinite(p.marginMin));
    }
    if (p.now.setpointW !== null) {
      rated++;
      assert.ok(p.now.setpointW >= 500 && p.now.setpointW <= limit && p.now.setpointW % 100 === 0, JSON.stringify(p.now));
      for (const t of p.trajectory) assert.ok(t.setpointW >= 500 && t.setpointW <= limit && t.setpointW % 100 === 0, JSON.stringify(t));
    }
    if (p.status === "OK") assert.equal(band(p).pessimisticHeld.reachedByDeadline, true, "OK never relies on a later change");
  }
  assert.ok(rated > 250, "rated " + rated);
});

test("MAJOR 4: before the window the SOC at the window start is the reading less the drain bound over the reading's age and the time to the window (by hand)", () => {
  // 600 W for 151 min (age 1 + 150 to the window) = 1.51 kWh, counted in the most points per kWh (0.289301 kWh per point): 5.2195 points, so 24.78 %
  const drained = 30 - (600 * 151) / 60 / 1000 / ((31.7 * 0.94) / 1.03 / 100);
  const early = plan({ elapsedMin: -150, socPct: 30, targetSocPct: 90, preWindowDrainW: 600 });
  const atStart = plan({ elapsedMin: 0, socPct: drained, targetSocPct: 90 });
  assert.equal(early.now.setpointW, atStart.now.setpointW, "the same rate as a window-start plan from the drained SOC");
  assert.ok((early.now.setpointW as number) > (plan({ elapsedMin: -150, socPct: 30, targetSocPct: 90, preWindowDrainW: 0 }).now.setpointW as number), "the drain raises the rate");
  assert.equal(early.status, "OK");
  assert.ok(early.codes.includes("BEFORE_WINDOW"));
  near(early.assumptions?.socAtPlanStartPct, drained, 0.006, "the SOC the plan starts from");
  assert.equal(plan({ socPct: 30 }).assumptions?.socAtPlanStartPct, 30, "in the window it is the reading");
  // the reading's age counts too: 3000 W over 15 + 150 min = 8.25 kWh = 28.52 points, so 71.48 % (an age of 1 min would leave 73.90 %)
  const aged = plan({ elapsedMin: -150, socPct: 100, targetSocPct: 100, preWindowDrainW: 3000, socAgeMin: 15 });
  near(aged.assumptions?.socAtPlanStartPct, 100 - (3000 * 165) / 60 / 1000 / ((31.7 * 0.94) / 1.03 / 100), 0.006, "the age is drained too");
  assert.ok((plan({ elapsedMin: -150, socPct: 30, targetSocPct: 90, preWindowDrainW: 600, socAgeMin: 15 }).now.setpointW as number) >= (early.now.setpointW as number));
  // the review's case without a drain bound: no OK the evening before (refused, the SOC at the window start is not known)
  for (const elapsedMin of [-1, -150, -720]) assert.equal(plan({ elapsedMin, socPct: 30, targetSocPct: 90 }).status, "INPUTS_UNUSABLE", String(elapsedMin));
  // a battery at the target now may not be at the window start
  assert.equal(plan({ elapsedMin: -300, socPct: 81, preWindowDrainW: 600 }).status, "OK");
  assert.equal(plan({ elapsedMin: -10, socPct: 85, preWindowDrainW: 0 }).status, "NO_NEED");
  // once the window is open the drain bound is ignored
  assert.deepEqual(plan({ preWindowDrainW: 5000 }).now, plan().now);
});

test("MAJOR 5: OK never relies on a later change: the owner-confirmed raise on the TOU editor gives TARGET_AT_RISK (the review's case: 3000 W in force, 5900 W needed)", () => {
  const p = plan({ socPct: 30, targetSocPct: 90, actuatorProfile: "TOU_SLOT_EDITOR", inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(p.now.neededW, 5900);
  assert.equal(p.now.change, "KEEP");
  assert.ok(p.codes.includes("HELD_DWELL"));
  assert.deepEqual(p.trajectory.map((t) => [t.atMin, t.setpointW, t.change, t.conditional]), [[0, 3000, "KEEP", false], [60, 6700, "INCREASE", true]], "the raise is still planned, conditionally");
  assert.equal(p.status, "TARGET_AT_RISK");
  assert.ok(p.codes.includes("RELIES_ON_LATER_CHANGE"));
  assert.equal(band(p).pessimistic.reachedByDeadline, true);
  assert.equal(band(p).pessimisticHeld.reachedByDeadline, false);
  assert.equal(p.marginMin, null, "judged with 3000 W held, the pessimistic world does not finish in the window");
  // every path that exists needs the owner per change or cannot change; the others do not exist: none makes a later change by itself
  for (const prof of Object.values(GENTLE_ACTUATOR_PROFILES)) assert.ok(!prof.existsToday || !prof.midWindowAdjustment || prof.ownerConfirmationPerChange, prof.id + " would make a later change by itself: revisit the status basis");
});

test("MAJOR 5: with no path named the most restrictive existing path (the Free Power start) is assumed and said; naming one removes the note", () => {
  const p = plan();
  assert.equal(p.profile?.id, "FREE_POWER_LEASE");
  assert.ok(p.codes.includes("PROFILE_DEFAULT_MOST_RESTRICTIVE"));
  assert.equal(p.trajectory.length, 1);
  assert.equal(p.profile?.existsToday, true);
  assert.equal(p.profile?.maxChanges, 0);
  for (const id of Object.keys(GENTLE_ACTUATOR_PROFILES)) assert.ok(!plan({ actuatorProfile: id as "UNCONSTRAINED" }).codes.includes("PROFILE_DEFAULT_MOST_RESTRICTIVE"), id);
  assert.equal(plan({ actuatorProfile: null as unknown as "UNCONSTRAINED" }).codes[0], "PROFILE_INVALID");
});

test("MAJOR 6: the grid headroom caps the rate even just below the ceiling, and a GRID_AC ceiling is converted (by hand)", () => {
  // (11000 - 1000 x 1.2) x 0.85 / 1.1 = 7572.7 W, floored to 7500 W: 500 W below the 8000 W ceiling
  const g = plan({ household: { gridImportLimitW: 11000, demandPeakW: 1000, demandAgeMin: 1 }, targetSocPct: 100 });
  assert.equal(g.now.ceilingW, 7500);
  assert.equal(g.now.ceilingName, "grid_headroom");
  assert.equal(g.now.setpointW, 7500, "best effort is the grid headroom, not the 8000 W ceiling");
  // a grid-side charge limit of 6000 W in setpoint units: 6000 x 0.85 / 1.1 = 4636 W, floored to 4600 W
  const ac = plan({ ceilings: [maxChargePowerCeiling(8000, 8000), { name: "grid_charge_limit", watts: 6000, basis: "GRID_AC" }] });
  assert.equal(ac.now.ceilingW, 4600);
  assert.equal(ac.now.ceilingName, "grid_charge_limit");
});

test("MAJOR 6: the OK / TARGET_AT_RISK boundary and the needed-rate search are exact to tenths of a minute (by hand)", () => {
  // 41 points from 19: E = 41 x cap x 1.06 / 0.97 / 100; 3900 W gives 3.51 kW at the battery. cap 31.3: 239.72 min; cap 31.4: 240.49 min (deadline 240)
  const finish = (cap: number, w: number): number => ((41 * cap * 1.06) / 0.97 / 100 / ((w * 0.9) / 1000)) * 60;
  const fixed = (cap: number) => plan({ capacityKwh: cap, targetSocPct: 60, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 } });
  near(band(fixed(31.3)).pessimisticHeld.finishMin, finish(31.3, 3900), 0.02, "cap 31.3");
  assert.equal(fixed(31.3).status, "OK");
  near(band(fixed(31.4)).pessimisticHeld.finishMin, finish(31.4, 3900), 0.02, "cap 31.4");
  assert.ok(finish(31.4, 3900) - 240 < 0.6);
  assert.equal(fixed(31.4).status, "TARGET_AT_RISK", "a miss of half a minute is not OK");
  assert.equal(fixed(31.4).marginMin, -0.5);
  // the search: at cap 31.4 the lowest rate is 4000 W (3900 W misses by 0.49 min); at cap 31.3 it is 3900 W (3800 W misses)
  assert.equal(plan({ capacityKwh: 31.4, targetSocPct: 60 }).now.setpointW, 4000);
  assert.equal(plan({ capacityKwh: 31.3, targetSocPct: 60 }).now.setpointW, 3900);
});

test("MAJOR 6: validation of the readings and the force record: a previous reading one minute in the future, a negative rate in force", () => {
  // one minute ahead with the same SOC: the jump and the regression checks would both pass it; only the time check refuses it
  assert.deepEqual(plan({ previousSoc: { socPct: 20, elapsedMin: 1 } }).codes, ["SOC_IMPLAUSIBLE"]);
  assert.equal(plan({ previousSoc: { socPct: 20, elapsedMin: 0 } }).status, "OK", "the same minute is fine");
  assert.deepEqual(gen({ inForce: { setpointW: -100, lastChangeAtMin: 0, changesUsed: 0 } }).codes, ["INPUT_INVALID"]);
});

test("MAJOR 6: a forced decrease below the ceiling does not draw on the change budget, an ordinary change does (now and in the projection)", () => {
  const forced = gen({ elapsedMin: 100, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 2 } });
  assert.equal(forced.now.change, "DECREASE");
  assert.equal(forced.profile?.changesLeft, 4, "6 - 2: the forced decrease is free");
  const raised = gen({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 2 } });
  assert.equal(raised.now.change, "INCREASE");
  assert.equal(raised.profile?.changesLeft, 3, "6 - 2 - 1");
  // one change left after a forced decrease: the expected world may still plan one later change, and only one
  const last = gen({ elapsedMin: 100, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 7000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 5 } });
  assert.equal(last.now.change, "DECREASE");
  assert.equal(last.trajectory.length, 2, JSON.stringify(last.trajectory));
  assert.equal(last.trajectory[1]?.conditional, true);
});

test("MAJOR 7 survivors: the optimistic band, a miss inside the buffer, the lowest rate, the SOC at the deadline, the buffer that fits, an unusable slot entry (by hand)", () => {
  // optimistic world, 4000 W START to 60 %: (60 - 20.5) x 0.289301 = 11.4274 kWh at 4 x 0.97 = 3.88 kW: 176.71 min
  near(band(plan({ targetSocPct: 60 })).optimistic.finishMin, (((60 - 20.5) * (31.7 * 0.94)) / 1.03 / 100 / 3.88) * 60, 0.05, "optimistic finish");
  // after the deadline with 6000 W held: 11 points x 0.346412 = 3.8105 kWh at 5.4 kW = 42.34 min, so 292.3 < 300: inside the buffer is TARGET_AT_RISK, not UNREACHABLE
  const late = plan({ elapsedMin: 250, socPct: 70, inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(late.status, "TARGET_AT_RISK");
  near(band(late).pessimisticHeld.finishMin, 250 + ((11 * PK) / 5.4) * 60, 0.05, "late finish");
  // the lowest rate is offered: 2 points x 0.346412 = 0.6928 kWh at 0.45 kW = 92.4 min
  const min = plan({ socPct: 79 });
  assert.equal(min.now.setpointW, 500);
  assert.ok(min.codes.includes("RATE_AT_MINIMUM"));
  // the SOC at the deadline, not the target: 3000 W for 180 min = 8.1 kWh = 23.38 points from 9, so 32.4
  const none = plan({ targetSocPct: 100, socPct: 10, bufferMin: 120, ceilings: [maxChargePowerCeiling(8000, 3000)] });
  assert.equal(none.status, "UNREACHABLE");
  assert.equal(band(none).pessimistic.socAtDeadlinePct, Math.round((9 + (2.7 * 3) / PK) * 10) / 10);
  // the buffer that fits rounds DOWN: 8000 W from 39 to 95: plateau 51 points 147.22 min, the cliff minute 0.1949 points, the tail 4.8051 points at
  // 0.9 kW 110.97 min: 259.2 min, 40.8 min before the window end, so 40 (not 45)
  const risk = plan({ targetSocPct: 95, socPct: 40 });
  near(band(risk).pessimisticHeld.finishMin, ((51 * PK) / 7.2) * 60 + 1 + ((95 - 90 - 0.5625 * (7.2 / 60 / PK)) * PK) / 0.9 * 60, 0.05, "pessimistic finish above the knee");
  assert.equal(risk.bufferThatWouldFitMin, 40);
  // a slot table with an entry that is not a slot gives no window
  assert.equal(windowFromSlotTable([slot(60, 5000, 90, "Grid"), null as never, slot(180, 5000, 15, "None")]), null);
});
