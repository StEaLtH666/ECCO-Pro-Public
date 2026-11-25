// Gentle night planner (src/gentleNight.ts): the safety properties an independent review found untested or wrong (BLOCKER 1 to 3, MAJOR 4 to 7), each
// pinned by a behavioural assertion with a value worked out BY HAND from the stated model (not copied from the code). READ ONLY: a pure function.
// The model numbers used below: pessimistic kWh per point = 31.7 x 1.06 / 0.97 / 100 = 0.346412, efficiency 0.90, start = reading - 1.0 (resolution 1,
// noise 0.5), knee 90, tail 1/8 after a one minute cliff; optimistic kWh per point = 31.7 x 0.94 / 1.03 / 100 = 0.289301, efficiency 0.97, start + 0.5.
import { test } from "node:test";
import assert from "node:assert/strict";
import { planGentleNight, windowFromSlotTable, NIGHT_CODES } from "../src/gentleNight.ts";
import type { GentleNightInput, GentleNightPlan, NightCode } from "../src/gentleNight.ts";
import { GENTLE_ACTUATOR_PROFILES, effectiveCeiling, maxChargePowerCeiling, smallestKnownCeiling } from "../src/gentleController.ts";
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
  // by hand, reading 90: the pessimistic world takes the worse of its two consistent starts (confirmation review MINOR: the earlier start on the tail at 89,
  // below its own knee, was a state the model cannot be in). Past the knee: AT the knee 90 on the tail, 225 W for 235 min: 0.88125 kWh = 2.544 points, so
  // 92.54. Not yet past it: the plateau from 89 at 1.8 kW (0.086603 points a minute) reaches 90 in 11.55 min, the cliff minute adds 0.0487 points, then the
  // tail 0.010825 points a minute for 222.45 min adds 2.408: 92.46. The lower of the two, shown FLOORED to a tenth (never above the exact value: round 3
  // review F6; it was rounded to 92.5 before, and 91.5 before that, kept as a killed mutant): 92.4
  assert.equal(band(gen({ elapsedMin: 5, socPct: 90, targetSocPct: 95, inForce })).pessimisticHeld.socAtDeadlinePct, 92.4, "SOC at the deadline");
  // the threshold also counts the charge possible since the reading (confirmation review BLOCKER): the reading is 1 min old and 2000 W is in force, so
  // 1 x 2000 x 1.1 / 60000 / 0.289301 = 0.1267 points: held from 90 - 1.0 - 0.1267 = 88.873 (inclusive). Just below it (88.8 + 1.1267 < 90) the knee is
  // surely ahead: the raise is credited and made; at 88.9 (90.027) it is held (88.9 was the first reading credited before, without the age)
  const below = gen({ elapsedMin: 5, socPct: 88.8, targetSocPct: 95, inForce });
  assert.equal(below.now.change, "INCREASE");
  assert.ok(!below.codes.includes("HELD_PAST_KNEE"));
  near(below.assumptions?.chargeSinceReadingPct, (2000 * 1.1) / 60000 / ((31.7 * 0.94) / 1.03 / 100), 0.006, "the charge since a 1 min old reading");
  const at = gen({ elapsedMin: 5, socPct: 88.9, targetSocPct: 95, inForce });
  assert.equal(at.now.change, "KEEP");
  assert.ok(at.codes.includes("HELD_PAST_KNEE"));
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
  // a START past the knee (nothing in force) crosses the knee AT the start, at the start rate (nothing has charged before: confirmation review MINOR, a START
  // is monotone in the SOC): the one-minute cliff delivers (1 + 0.125) / 2 of the plateau, then the tail. 3900 W: plateau 3.51 kW / 60 / 0.346412 = 0.16888
  // points a minute, the cliff 0.0950 points, the tail 0.021110 points a minute: (3 - 0.0950) / 0.021110 + 1 = 138.6 min <= 140. 3800 W: 0.16455, the cliff
  // 0.0926, the tail 0.020569: 142.4 min > 140. So 3900 W (4000 W before, when the fall was taken as already over at a START: kept as a killed mutant)
  const start = gen({ elapsedMin: 100, socPct: 93, targetSocPct: 95 });
  assert.equal(start.now.change, "START");
  assert.equal(start.now.setpointW, 3900);
  near(band(start).pessimisticHeld.finishMin, 100 + 1 + (3 - (1.125 / 2) * ((3.51 / 60) / PK)) / (0.125 * (3.51 / 60) / PK), 0.15, "the START's pessimistic finish");
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
    // the same seeded draws in the same order as before; a last change drawn after now is refused since the confirmation review (MINOR), so the sweep
    // takes it as made now, and the drawn record itself must be refused
    const actuatorProfile = profiles[Math.floor(r() * 4)] as (typeof profiles)[number];
    const elapsedMin = Math.floor(r() * 300);
    const socPct = Math.floor(r() * 1000) / 10;
    const targetSocPct = 60 + Math.floor(r() * 41);
    const drawnChangeAt = Math.floor(r() * 200) - 60;
    const changesUsed = Math.floor(r() * 3);
    const over: Partial<GentleNightInput> = { actuatorProfile, elapsedMin, socPct, targetSocPct, ceilings: [maxChargePowerCeiling(8000, limit)] };
    const p = plan({ ...over, inForce: { setpointW: w, lastChangeAtMin: Math.min(drawnChangeAt, elapsedMin), changesUsed } });
    if (drawnChangeAt > elapsedMin) {
      const q = plan({ ...over, inForce: { setpointW: w, lastChangeAtMin: drawnChangeAt, changesUsed } });
      assert.ok(q.codes.includes("INPUT_INVALID") && q.now.setpointW === null && q.band === null, "a last change after now is refused: " + q.codes.join(","));
    }
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
  // once the window is open the drain still counts while nothing charges (confirmation review MAJOR 3; "ignored once the window is open" before): a START
  // counts it over the reading's age, 5000 W for 1 min = 0.08333 kWh = 0.2881 points; a rate in force charges, so with a reading taken in the window none
  near(plan({ preWindowDrainW: 5000 }).assumptions?.socAtPlanStartPct, 20 - 5000 / 60 / 1000 / ((31.7 * 0.94) / 1.03 / 100), 0.006, "a START counts the drain over the age");
  assert.equal(gen({ preWindowDrainW: 5000, elapsedMin: 30, inForce: { setpointW: 4000, lastChangeAtMin: 0, changesUsed: 0 } }).assumptions?.socAtPlanStartPct, 20, "a rate in force: no drain");
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
  // the SOC at the deadline, not the target: 3000 W for 180 min = 8.1 kWh = 23.38 points from 9 = 32.38, shown FLOORED to a tenth (round 3 review F6: never above
  // the exact value; it was rounded to 32.4 before): 32.3
  const none = plan({ targetSocPct: 100, socPct: 10, bufferMin: 120, ceilings: [maxChargePowerCeiling(8000, 3000)] });
  assert.equal(none.status, "UNREACHABLE");
  assert.equal(band(none).pessimistic.socAtDeadlinePct, Math.floor((9 + (2.7 * 3) / PK) * 10) / 10);
  // the buffer that fits rounds DOWN: 8000 W from 39 to 95: plateau 51 points 147.22 min, the cliff minute 0.1949 points, the tail 4.8051 points at
  // 0.9 kW 110.97 min: 259.2 min, 40.8 min before the window end, so 40 (not 45)
  const risk = plan({ targetSocPct: 95, socPct: 40 });
  near(band(risk).pessimisticHeld.finishMin, ((51 * PK) / 7.2) * 60 + 1 + ((95 - 90 - 0.5625 * (7.2 / 60 / PK)) * PK) / 0.9 * 60, 0.05, "pessimistic finish above the knee");
  assert.equal(risk.bufferThatWouldFitMin, 40);
  // a slot table with an entry that is not a slot gives no window
  assert.equal(windowFromSlotTable([slot(60, 5000, 90, "Grid"), null as never, slot(180, 5000, 15, "None")]), null);
});

// ---- the independent confirmation review of 52ed09e (2 BLOCKER, 1 MAJOR, 5 MINOR, 11 surviving mutants): each pinned by a behavioural assertion ----------
// More model numbers: the fewest kWh per point (the most points per kWh) for the trusted 31.7 kWh = 31.7 x 0.94 / 1.03 / 100 = 0.289301 (the drain and the
// charge possible since a reading are counted in it), and the most realised power = the overshoot allowance 1.1 x the setpoint (above the best efficiency).
const OPT = (31.7 * 0.94) / 1.03 / 100;
const rc3000 = { setpointW: 3000, lastChangeAtMin: -60, changesUsed: 0 };
const lease8000 = { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 };

test("confirmation BLOCKER 1: the knee estimate counts the charge possible since the reading (age x rate in force x 1.1 in the most points per kWh) (by hand)", () => {
  // 15 min at 3000 W: 15 x 3000 x 1.1 / 60000 / 0.289301 = 2.8517 points, so a rate in force is held from the reading 90 - 1.0 - 2.8517 = 86.148
  const at = (socPct: number, socAgeMin: number): GentleNightPlan => plan({ actuatorProfile: "RATE_CONTROLLER_PROPOSED", elapsedMin: 20, socAgeMin, socPct, targetSocPct: 95, inForce: rc3000 });
  const held = at(86.2, 15);
  near(held.assumptions?.chargeSinceReadingPct, (15 * 3000 * 1.1) / 60000 / OPT, 0.006, "the charge since the reading");
  near(held.assumptions?.kneeEstimatePct, 86.2 + 1 + (15 * 3000 * 1.1) / 60000 / OPT, 0.006, "the knee estimate");
  assert.equal(held.now.change, "KEEP");
  assert.ok(held.codes.includes("HELD_PAST_KNEE"));
  assert.notEqual(held.status, "OK");
  assert.equal(held.now.neededMeetsDeadline, false, "past the knee the tail is anchored at 3000 W: 337.5 W from the knee 90 does not reach 95 in 220 min");
  // just below the threshold (89.95 < 90) the knee is surely ahead: the raise is credited; the same reading 1 min old (0.19 points) likewise
  assert.equal(at(86.1, 15).now.change, "INCREASE");
  const fresh = at(86.2, 1);
  assert.equal(fresh.now.change, "INCREASE");
  near(fresh.assumptions?.chargeSinceReadingPct, (1 * 3000 * 1.1) / 60000 / OPT, 0.006, "1 min of age");
  // nothing charges before the window opens: a reading taken 15 min before minute 5 counts those 5 min only (0.9506 points); the 10 min before the window
  // need a drain bound (the battery supplied the house: MAJOR 3)
  const early = plan({ actuatorProfile: "RATE_CONTROLLER_PROPOSED", elapsedMin: 5, socAgeMin: 15, socPct: 86.2, targetSocPct: 95, inForce: rc3000, drainBoundW: 0 });
  near(early.assumptions?.chargeSinceReadingPct, (5 * 3000 * 1.1) / 60000 / OPT, 0.006, "only the window part of the age charges");
  assert.equal(early.assumptions?.idleSinceReadingMin, 10);
  // a change made after the reading: before it the rate is not known, so the firmware bound: 10 min at 8000 W, then 5 min at 3000 W: 6.0203 points. Since round 3
  // (F1) those 10 minutes also count as idle for the SOC, so they need a drain bound (0 W here: the knee estimate does not use the drain); without one the input
  // is refused (the same record was planned with those minutes dropped before)
  const changedIn = { actuatorProfile: "RATE_CONTROLLER_PROPOSED", elapsedMin: 20, socAgeMin: 15, socPct: 80, targetSocPct: 95, inForce: { setpointW: 3000, lastChangeAtMin: 15, changesUsed: 1 } } as const;
  assert.deepEqual(plan(changedIn).codes, ["DRAIN_UNKNOWN_AGED_READING"]);
  const changed = plan({ ...changedIn, drainBoundW: 0 });
  near(changed.assumptions?.chargeSinceReadingPct, ((10 * 8000 + 5 * 3000) * 1.1) / 60000 / OPT, 0.006, "an unknown rate before a change after the reading");
  // the most points per kWh: a learned capacity SMALLER than the trusted one counts (25 kWh: 3.616 points)
  const small = plan({ actuatorProfile: "RATE_CONTROLLER_PROPOSED", elapsedMin: 20, socAgeMin: 15, socPct: 80, targetSocPct: 95, inForce: rc3000, learnedCapacityKwh: 25 });
  near(small.assumptions?.chargeSinceReadingPct, (15 * 3000 * 1.1) / 60000 / ((25 * 0.94) / 1.03 / 100), 0.006, "the smaller learned capacity");
});

test("confirmation BLOCKER 1 / MINOR: past the knee the pessimistic world is the WORSE of its two consistent starts; before the window a slot power set has not charged (by hand)", () => {
  // reading 86.2 15 min old, 3000 W in force, target 91 (held: the estimate 90.05): past the knee, from the knee 90 on the tail 0.125 x 2.7 = 0.3375 kW: 1 point
  // x 0.346412 kWh in 61.58 min; NOT yet past it, from 85.2 on the plateau (0.129904 points a minute) 4.8 points in 36.95 min, the cliff minute 0.0731, then the
  // tail 0.016238 points a minute for the 0.9269 left: 57.08 min, 95.03 min in all. The later of the two: the plateau start, at minute 20 + 95.03
  const both = plan({ actuatorProfile: "RATE_CONTROLLER_PROPOSED", elapsedMin: 20, socAgeMin: 15, socPct: 86.2, targetSocPct: 91, inForce: rc3000 });
  assert.equal(both.now.change, "KEEP");
  const perMin = 2.7 / 60 / PK;
  near(band(both).pessimisticHeld.finishMin, 20 + 4.8 / perMin + 1 + (1 - (1.125 / 2) * perMin) / (0.125 * perMin), 0.1, "the later of the two starts");
  assert.equal(both.status, "OK", "each start makes the deadline 240 (the battery is in one of the two cases)");
  // the rate needed decides on both starts too: the plateau start needs 4.8 points x 0.346412 / (0.9 S) + 1 + (1 - cliff) x 0.346412 / (0.1125 S) <= 220 min:
  // 1300 W gives 223.9 min, 1400 W 207.6 min, so 1400 W (the past start alone would accept 900 W: 0.1125 x 900 W carries the 1 point in 205 min)
  assert.equal(both.now.neededW, 1400);
  // and the start past the knee can be the later one: reading 90.9 with 8000 W in force (held), the plateau start from 89.9 reaches 90 in 0.29 min, its
  // cliff minute carries 0.195 points, then the tail 900 W; the start past it carries all 5 points on the tail: 5 x 0.346412 / 0.9 x 60 = 115.47 min, 3.2 min later
  const late = gen({ elapsedMin: 100, socPct: 90.9, targetSocPct: 95, inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(late.now.change, "KEEP");
  near(band(late).pessimisticHeld.finishMin, 100 + ((5 * PK) / 0.9) * 60, 0.1, "the start past the knee, the later one here");
  // the threshold is inclusive: a reading of age 0 adds nothing, so 89 + 1.0 = 90 is held and 88.99 is not
  const exact = (socPct: number): GentleNightPlan => gen({ elapsedMin: 5, socAgeMin: 0, socPct, targetSocPct: 95, inForce: { setpointW: 2000, lastChangeAtMin: -60, changesUsed: 0 } });
  assert.ok(exact(89).codes.includes("HELD_PAST_KNEE"));
  assert.equal(exact(88.99).now.change, "INCREASE");
  // before the window (TOU, 2000 W set, reading 92, 30 min before, drain 0): nothing has charged yet, the knee is crossed at the window start at the rate in
  // force then, so the raise is credited like a START (the review: KEEP AT_RISK before, while a START gave 3100 OK). From 91, crossed at the start: the cliff
  // minute 0.5625 and 239 min of the tail 0.125 of the plateau must give 4 points: plateau 0.13142 points a minute, so 3035 W: 3100 W
  const tou = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: -30, drainBoundW: 0, socPct: 92, targetSocPct: 95, inForce: { setpointW: 2000, lastChangeAtMin: -200, changesUsed: 0 } });
  const start = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: -30, drainBoundW: 0, socPct: 92, targetSocPct: 95 });
  assert.equal(start.now.setpointW, 3100);
  assert.equal(tou.now.change, "INCREASE");
  assert.equal(tou.now.setpointW, 3100);
  assert.equal(tou.status, "OK");
  assert.ok(!tou.codes.includes("HELD_PAST_KNEE"));
  assert.equal(tou.assumptions?.chargeSinceReadingPct, 0);
});

test("confirmation MINOR: a START is monotone in the SOC with targets ABOVE the knee: a higher reading never needs a higher rate nor gets a worse status (before the window too)", () => {
  const rank: Record<string, number> = { OK: 0, TARGET_AT_RISK: 1, UNREACHABLE: 2 };
  let compared = 0;
  for (const targetSocPct of [91, 93, 95, 97, 100]) {
    for (const elapsedMin of [-30, 0, 100, 180]) {
      for (const capacityKwh of [20, 31.7]) {
        for (const bufferMin of [0, 60]) {
          let prev: GentleNightPlan | null = null;
          for (let s = 850; s <= 999; s++) {
            const socPct = s / 10;
            const p = plan({ targetSocPct, elapsedMin, capacityKwh, bufferMin, socPct, drainBoundW: 0, actuatorProfile: "FREE_POWER_LEASE" });
            if (p.now.change !== "START") {
              prev = null;
              continue;
            }
            if (prev !== null) {
              compared++;
              const what = JSON.stringify({ targetSocPct, elapsedMin, capacityKwh, bufferMin, socPct });
              assert.ok((p.now.setpointW as number) <= (prev.now.setpointW as number), "a higher reading raised the START: " + what);
              assert.ok((rank[p.status] as number) <= (rank[prev.status] as number), "a higher reading made the status worse: " + what + " " + prev.status + " to " + p.status);
            }
            prev = p;
          }
        }
      }
    }
  }
  assert.ok(compared > 4000, "compared " + compared);
  // the review's case, t = 100, target 95: 88.9 OK 6800 W, 89.0 TARGET_AT_RISK 8000 W, 90 OK 8000 W before; now all OK and falling
  const r = (socPct: number): [string, number | null] => {
    const p = plan({ elapsedMin: 100, socPct, targetSocPct: 95, actuatorProfile: "FREE_POWER_LEASE" });
    return [p.status, p.now.setpointW];
  };
  assert.deepEqual([r(88.9), r(89), r(90)], [["OK", 6800], ["OK", 6800], ["OK", 6600]]);
});

// BLOCKER 2: every refusal after the parameters and the path are known. The lease (fixed rate) has 8000 W in force since before the window; the owner
// limit is 6000 W unless the case says otherwise. [the path, the input, the refusal's own code, the known ceiling it breaches, its name]
const EARLY: Array<[string, Partial<GentleNightInput>, NightCode, number, string]> = [
  ["a target outside 10 to 100", { targetSocPct: 5 }, "TARGET_INVALID", 6000, "max_charge_power_effective"],
  ["a buffer off the 5 minute step", { bufferMin: 7 }, "BUFFER_INVALID", 6000, "max_charge_power_effective"],
  ["no charge window", { chargeWindow: null as unknown as { startMin: number; endMin: number } }, "WINDOW_INVALID", 6000, "max_charge_power_effective"],
  ["an invalid clock day", { clockDay: { changeAtMin: 120, deltaMin: 30 } as unknown as GentleNightInput["clockDay"] }, "CLOCK_DAY_INVALID", 6000, "max_charge_power_effective"],
  ["a clock-change night", { clockDay: { changeAtMin: 120, deltaMin: 60 } }, "CLOCK_CHANGE_NIGHT", 6000, "max_charge_power_effective"],
  ["an elapsed time that is not a number", { elapsedMin: NaN }, "ELAPSED_INVALID", 6000, "max_charge_power_effective"],
  ["no SOC", { socPct: null }, "NO_SOC", 6000, "max_charge_power_effective"],
  ["a stale SOC", { socAgeMin: 30 }, "STALE_SOC", 6000, "max_charge_power_effective"],
  ["a SOC above 100", { socPct: 101 }, "SOC_IMPLAUSIBLE", 6000, "max_charge_power_effective"],
  ["a SOC jump against the previous reading", { previousSoc: { socPct: 10, elapsedMin: 55 } }, "SOC_IMPLAUSIBLE", 6000, "max_charge_power_effective"],
  ["no usable capacity", { capacityKwh: 0 }, "CAPACITY_UNUSABLE", 6000, "max_charge_power_effective"],
  ["a last change after now", { inForce: { setpointW: 8000, lastChangeAtMin: 100, changesUsed: 0 } }, "INPUT_INVALID", 6000, "max_charge_power_effective"],
  ["two drain bounds that disagree", { drainBoundW: 100, preWindowDrainW: 200 }, "INPUT_INVALID", 6000, "max_charge_power_effective"],
  ["no drain bound before the window", { elapsedMin: -30 }, "PRE_WINDOW_DRAIN_UNKNOWN", 6000, "max_charge_power_effective"],
  ["no drain bound for a reading taken before the window", { elapsedMin: 5, socAgeMin: 15 }, "DRAIN_UNKNOWN_AGED_READING", 6000, "max_charge_power_effective"],
  ["the reading at the target (the lease has no stop at a target SOC)", { socPct: 80 }, "AT_TARGET", 6000, "max_charge_power_effective"],
  ["the window over", { elapsedMin: 300 }, "WINDOW_OVER", 6000, "max_charge_power_effective"],
  ["only a stale ceiling (a stale lower value still caps)", { ceilings: [maxChargePowerCeiling(8000, 6000, 90)] }, "NO_SAFE_CEILING", 6000, "max_charge_power_effective"],
  ["no ceiling list (the firmware bound, 9000 W in force)", { ceilings: null as unknown as GentleNightInput["ceilings"], inForce: { setpointW: 9000, lastChangeAtMin: -60, changesUsed: 0 } }, "NO_SAFE_CEILING", 8000, "firmware_setpoint_bound"],
  ["a grid limit that is not a number", { household: { gridImportLimitW: -5 } }, "INPUT_INVALID", 6000, "max_charge_power_effective"],
  ["a stale grid limit (6000 W: the headroom 4636 W)", { ceilings: [maxChargePowerCeiling(8000, 8000)], household: { gridImportLimitW: 6000, gridImportLimitAgeMin: 90, demandPeakW: 0, demandAgeMin: 1 } }, "GRID_LIMIT_STALE", 4600, "grid_headroom"],
  ["a grid limit with the demand unknown (the limit alone: 6000 x 0.85 / 1.1 = 4636 W)", { ceilings: [maxChargePowerCeiling(8000, 8000)], household: { gridImportLimitW: 6000 } }, "DEMAND_UNKNOWN", 4600, "grid_import_limit"],
  ["a grid headroom below the minimum (3000 - 2500 x 1.2 = 0)", { ceilings: [maxChargePowerCeiling(8000, 8000)], household: { gridImportLimitW: 3000, demandPeakW: 2500, demandAgeMin: 1 } }, "HEADROOM_BELOW_MIN", 0, "grid_headroom"],
  ["an owner limit below the minimum (300 W)", { ceilings: [maxChargePowerCeiling(8000, 300)] }, "CEILING_BELOW_MIN", 300, "max_charge_power_effective"],
];
for (const [path, over, code, ceilingW, ceilingName] of EARLY) {
  test("confirmation BLOCKER 2, early return '" + path + "': a lease rate in force above a known ceiling gives STOP_RECOMMENDED, never 'the fallback holds whatever is in force'", () => {
    const p = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { ...lease8000, lastChangeAtMin: -60 }, ...over });
    assert.equal(p.status, "STOP_RECOMMENDED", p.codes.join(","));
    assert.equal(p.stopRecommended, true);
    assert.equal(p.now.change, "STOP");
    assert.equal(p.now.setpointW, null);
    assert.deepEqual(p.trajectory, []);
    assert.equal(p.expectedFinish, null);
    assert.equal(p.codes[0], code, p.codes.join(","));
    assert.ok(p.codes.includes("FORCED_BELOW_CEILING") && p.codes.includes("ACTUATOR_FIXED_RATE"), p.codes.join(","));
    assert.equal(p.now.ceilingW, ceilingW);
    assert.equal(p.now.ceilingName, ceilingName);
    assert.match(p.needed.join(" "), /Stop the charge on this path: the rate in force \(\d+ W\) is above the safe ceiling/);
    assert.doesNotMatch(p.needed.join(" "), /fallback holds/);
    assert.equal(p.profile?.id, "FREE_POWER_LEASE");
    assert.equal(p.actuationSupported, false);
  });
}

test("confirmation BLOCKER 2: on a path that can change, an early return with a rate above a known ceiling never says the fallback holds it (a STOP when no setpoint is that low, else it must come down); no breach keeps the plain refusal", () => {
  // the editor, 2000 W in force, the owner limit lowered to 300 W: no setpoint on any path is that low, so a STOP (not ACTUATOR_FIXED_RATE: the path can change)
  const low = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 300)], inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(low.status, "STOP_RECOMMENDED");
  assert.deepEqual(low.codes, ["CEILING_BELOW_MIN", "FORCED_BELOW_CEILING"]);
  assert.match(low.needed.join(" "), /which is below the lowest setpoint \(500 W\), so no setpoint is safe/);
  // the editor, 8000 W in force above 6000 W, the SOC unknown: the refusal stays (a lower setpoint is possible), with the forced decrease said
  const tou = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 60, socPct: null, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: lease8000 });
  assert.equal(tou.status, "INPUTS_UNUSABLE");
  assert.deepEqual(tou.codes, ["NO_SOC", "FORCED_BELOW_CEILING"]);
  assert.equal(tou.now.ceilingW, 6000);
  assert.equal(tou.stopRecommended, false);
  assert.match(tou.needed.join(" "), /must come down to at most 6000 W whatever else is unknown/);
  assert.doesNotMatch(tou.needed.join(" "), /fallback holds/);
  // no breach: at the ceiling, the lease keeps the plain refusal and its text
  const fine = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: null, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(fine.status, "INPUTS_UNUSABLE");
  assert.deepEqual(fine.codes, ["NO_SOC"]);
  assert.match(fine.needed.join(" "), /the fallback holds whatever is in force/);
  // before the parameters and the path are known these two refusals used to stay plain whatever was in force (the documented exclusions, "no STOP can be decided");
  // round 3 F3 removes them: with nothing in force, or a rate at the ceiling, they are still the plain refusals
  assert.deepEqual(plan({ actuatorProfile: "FREE_POWER_LEASE", params: { setpointOvershoot: 2 }, ceilings: [maxChargePowerCeiling(8000, 6000)] }).codes, ["PARAMS_INVALID"]);
  assert.deepEqual(plan({ actuatorProfile: "MAGIC" as unknown as "UNCONSTRAINED", ceilings: [maxChargePowerCeiling(8000, 6000)] }).codes, ["PROFILE_INVALID"]);
  assert.deepEqual(plan({ actuatorProfile: "FREE_POWER_LEASE", params: { setpointOvershoot: 2 }, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } }).codes, ["PARAMS_INVALID"]);
  // ... and with 8000 W in force above the 6000 W owner limit they are a STOP on a path that cannot lower the rate (the changed expectation: it was ["PARAMS_INVALID"] and
  // ["PROFILE_INVALID"] with the text "the fallback holds whatever is in force")
  const badParams = plan({ actuatorProfile: "FREE_POWER_LEASE", params: { setpointOvershoot: 2 }, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: lease8000 });
  assert.equal(badParams.status, "STOP_RECOMMENDED");
  assert.deepEqual(badParams.codes, ["PARAMS_INVALID", "FORCED_BELOW_CEILING", "ACTUATOR_FIXED_RATE"]);
  const badProfile = plan({ actuatorProfile: "MAGIC" as unknown as "UNCONSTRAINED", ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: lease8000 });
  assert.equal(badProfile.status, "STOP_RECOMMENDED");
  assert.deepEqual(badProfile.codes, ["PROFILE_INVALID", "FORCED_BELOW_CEILING", "ACTUATOR_FIXED_RATE"]);
  assert.equal(badProfile.profile, null);
});

test("confirmation survivors R05, R06, R09, R07 and MINOR: a STOP gives the needed rate at the ceiling, no finish, margin or fit, and the band of the rate in force; an off-step rate above the ceiling is forced or stopped (by hand)", () => {
  // R05: the rate a new START would need, at or below the ceiling: 41 points x 0.346412 = 14.2029 kWh in 180 min: 4.7343 kW / 0.9 = 5260 W, so 5300 W (not 8000)
  const stop = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: lease8000 });
  assert.equal(stop.status, "STOP_RECOMMENDED");
  assert.equal(stop.now.neededW, 5300);
  assert.equal(stop.now.neededMeetsDeadline, true);
  // MINOR: nothing is recommended to finish, so no expected finish, margin or buffer that fits; the band is what happens if nothing is done
  assert.equal(stop.expectedFinish, null);
  assert.equal(stop.marginMin, null);
  assert.equal(stop.bufferThatWouldFitMin, null);
  assert.ok(stop.band !== null);
  // R06: past the knee the band is the 8000 W in force: from 92 on the tail 0.125 x 8000 x 0.9 = 900 W, 3 points x 0.346412 = 1.03924 kWh in 69.28 min (not the
  // 6000 W ceiling: 675 W, 92.38 min)
  const knee = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 93, targetSocPct: 95, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: lease8000 });
  assert.equal(knee.status, "STOP_RECOMMENDED");
  near(band(knee).pessimisticHeld.finishMin, 60 + ((3 * PK) / 0.9) * 60, 0.1, "the band of the rate in force past the knee");
  // R09: 6050 W in force above the 6000 W ceiling is off the step yet above the ceiling: forced down on the editor, stopped on the lease (the main-path STOP,
  // with the band of the 6050 W in force: 14.2029 kWh at 5.445 kW = 156.50 min), never IN_FORCE_INVALID
  const tou = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 6050, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(tou.now.change, "DECREASE");
  assert.equal(tou.now.setpointW, 6000);
  assert.ok(tou.codes.includes("FORCED_BELOW_CEILING") && !tou.codes.includes("IN_FORCE_INVALID"));
  const free = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 6050, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(free.status, "STOP_RECOMMENDED");
  near(band(free).pessimisticHeld.finishMin, 60 + ((41 * PK) / 5.445) * 60, 0.1, "the band of 6050 W");
  // R07: the editor with no ordinary change left by the parameters can still lower the slot power (a forced decrease ignores the budget): not a STOP
  const none = plan({ actuatorProfile: "TOU_SLOT_EDITOR", params: { maxChanges: 0 }, elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: lease8000 });
  assert.equal(none.status, "OK");
  assert.equal(none.now.change, "DECREASE");
  assert.equal(none.now.setpointW, 6000);
  assert.equal(none.stopRecommended, false);
});

test("confirmation survivors R01, R10, R11, R12, R15, R19, R21 (by hand)", () => {
  // R01: the expected world starts past ITS OWN knee (95) from 96 with 3000 W in force: the fall over, the tail 0.2 x 3000 x 0.95 = 570 W: 4 points x 0.317 kWh
  // = 1.268 kWh in 133.47 min, from minute 60 (held: past the knee the policy holds)
  const r01 = plan({ actuatorProfile: "RATE_CONTROLLER_PROPOSED", elapsedMin: 60, socPct: 96, targetSocPct: 100, inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 } });
  near(band(r01).expected.finishMin, 60 + ((4 * 0.317) / 0.57) * 60, 0.1, "the expected world past its own knee");
  // R10: 0 W in force is a START that keeps the change count given: 6 of 6 used, so no later change is planned
  const r10 = gen({ elapsedMin: 60, socPct: 40, inForce: { setpointW: 0, lastChangeAtMin: 50, changesUsed: 6 } });
  assert.equal(r10.now.change, "START");
  assert.equal(r10.profile?.changesLeft, 0);
  assert.equal(r10.trajectory.length, 1);
  // R11 (MINOR): the drain is counted in the most points per kWh, with the SMALLER of the trusted and learned capacity: 600 W for 151 min = 1.51 kWh; 25 kWh
  // learned: / (25 x 0.94 / 1.03 / 100 = 0.228155) = 6.618 points, so 23.38; 36 kWh learned: the trusted 31.7 counts, 24.78 (not 25.40)
  near(plan({ elapsedMin: -150, socPct: 30, targetSocPct: 90, preWindowDrainW: 600, learnedCapacityKwh: 25 }).assumptions?.socAtPlanStartPct, 30 - 1.51 / ((25 * 0.94) / 1.03 / 100), 0.006, "learned 25");
  near(plan({ elapsedMin: -150, socPct: 30, targetSocPct: 90, preWindowDrainW: 600, learnedCapacityKwh: 36 }).assumptions?.socAtPlanStartPct, 30 - 1.51 / OPT, 0.006, "learned 36");
  // R12: the drained SOC is clamped at 0: 30 kW for 721 min empties it, and the plan is the plan from 0 at the window start
  const r12 = plan({ elapsedMin: -720, socPct: 10, targetSocPct: 90, preWindowDrainW: 30000 });
  assert.equal(r12.assumptions?.socAtPlanStartPct, 0);
  const zero = plan({ socPct: 0, targetSocPct: 90 });
  assert.deepEqual([r12.status, r12.now.setpointW, r12.band], [zero.status, zero.now.setpointW, zero.band]);
  // R15: the buffer that would fit is judged with the rate in force HELD: 3900 W from 19 to 60: 14.2029 kWh at 3.51 kW = 242.78 min, 57.2 min before the window
  // end, so 55 (the planned raise would give 60)
  const r15 = gen({ targetSocPct: 60, inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 } });
  near(band(r15).pessimisticHeld.finishMin, ((41 * PK) / 3.51) * 60, 0.05, "the held finish");
  assert.equal(r15.bufferThatWouldFitMin, 55);
  // R19: a target just above the knee (90.5, 91) is held past it like any other: 2000 W kept, no decrease
  for (const targetSocPct of [90.5, 91]) {
    const r19 = gen({ elapsedMin: 5, socPct: 90, targetSocPct, inForce: { setpointW: 2000, lastChangeAtMin: -60, changesUsed: 0 } });
    assert.equal(r19.now.change, "KEEP", String(targetSocPct));
    assert.ok(r19.codes.includes("HELD_PAST_KNEE"), String(targetSocPct));
  }
  // R21 (MINOR): the grid headroom caps even 94 W below the ceiling: (9358 - 1429 x 1.2) x 0.85 / 1.1 = 5906.1 W, floored to 5900 W, under the 6000 W limit
  const r21 = plan({ ceilings: [maxChargePowerCeiling(8000, 6000)], household: { gridImportLimitW: 9358, demandPeakW: 1429, demandAgeMin: 1 } });
  assert.equal(r21.now.ceilingW, 5900);
  assert.equal(r21.now.ceilingName, "grid_headroom");
  assert.equal(r21.now.setpointW, 5900);
});

test("confirmation MAJOR 3: inside the window a START counts the drain over the reading's age (continuous at the window start); a bound is needed beyond 2 min; a rate in force only for the part before the window (by hand)", () => {
  // a 15 min old reading of 40, 3000 W: at -0.5 the drain runs 15.5 min (2.679 points), at 0 and +0.5 15 min (2.593 points); the START from 1.0 below that to
  // 80: at 0, 43.59 points x 0.346412 = 15.100 kWh in 240 min = 4195 W: 4200 W; at -0.5, 15.131 kWh: 4203 W: 4300 W; at +0.5, 239.5 min: 4203 W: 4300 W
  const at = (elapsedMin: number): GentleNightPlan => plan({ elapsedMin, socPct: 40, socAgeMin: 15, drainBoundW: 3000, targetSocPct: 80 });
  near(at(-0.5).assumptions?.socAtPlanStartPct, 40 - (3000 * 15.5) / 60000 / OPT, 0.006, "-0.5");
  near(at(0).assumptions?.socAtPlanStartPct, 40 - (3000 * 15) / 60000 / OPT, 0.006, "0");
  near(at(0.5).assumptions?.socAtPlanStartPct, 40 - (3000 * 15) / 60000 / OPT, 0.006, "+0.5");
  assert.deepEqual([at(-0.5).now.setpointW, at(0).now.setpointW, at(0.5).now.setpointW], [4300, 4200, 4300]);
  // without a bound: up to 2 min not counted (and said), longer refused; the limit is a parameter
  assert.ok(plan({ socAgeMin: 2 }).codes.includes("DRAIN_NOT_COUNTED"));
  assert.ok(!plan({ socAgeMin: 2, drainBoundW: 0 }).codes.includes("DRAIN_NOT_COUNTED"));
  assert.deepEqual(plan({ socAgeMin: 2.5 }).codes, ["DRAIN_UNKNOWN_AGED_READING"]);
  assert.equal(plan({ socAgeMin: 2.5, params: { maxUncountedDrainMin: 3 } }).status, "OK");
  assert.deepEqual(plan({ params: { maxUncountedDrainMin: 0 } }).codes, ["DRAIN_UNKNOWN_AGED_READING"]);
  assert.deepEqual(plan({ params: { maxUncountedDrainMin: 16 } }).codes, ["PARAMS_INVALID"]);
  // a rate in force charges: a reading taken in the window needs no bound; one taken 10 min before the window opened needs it for those 10 min (1.728 points)
  const inForce = { setpointW: 4000, lastChangeAtMin: 0, changesUsed: 0 };
  assert.equal(gen({ elapsedMin: 30, socPct: 40, socAgeMin: 15, inForce }).assumptions?.idleSinceReadingMin, 0);
  assert.deepEqual(gen({ elapsedMin: 5, socPct: 40, socAgeMin: 15, inForce }).codes, ["DRAIN_UNKNOWN_AGED_READING"]);
  near(gen({ elapsedMin: 5, socPct: 40, socAgeMin: 15, drainBoundW: 3000, inForce }).assumptions?.socAtPlanStartPct, 40 - (3000 * 10) / 60000 / OPT, 0.006, "the part before the window");
  // the earlier name still works, and when both names are given they must agree
  assert.deepEqual(plan({ elapsedMin: -90, preWindowDrainW: 600 }).now, plan({ elapsedMin: -90, drainBoundW: 600 }).now);
  assert.deepEqual(plan({ elapsedMin: -90, preWindowDrainW: 600, drainBoundW: 600 }).now, plan({ elapsedMin: -90, drainBoundW: 600 }).now);
  assert.deepEqual(plan({ elapsedMin: -90, preWindowDrainW: 600, drainBoundW: 700 }).codes, ["INPUT_INVALID"]);
});

test("confirmation MINOR: a last change after now is refused (INPUT_INVALID); one made now holds by the dwell", () => {
  assert.deepEqual(gen({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 1e6, changesUsed: 0 } }).codes, ["INPUT_INVALID"]);
  assert.deepEqual(gen({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 100.5, changesUsed: 0 } }).codes, ["INPUT_INVALID"]);
  const now = gen({ elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 100, changesUsed: 0 } });
  assert.equal(now.now.change, "KEEP");
  assert.ok(now.codes.includes("HELD_DWELL"));
  assert.notEqual(plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: -30, drainBoundW: 0, inForce: { setpointW: 4000, lastChangeAtMin: -200, changesUsed: 0 } }).status, "INPUTS_UNUSABLE");
});

test("confirmation MINOR: what is needed on the TOU editor follows the change: a forced decrease mid-window ignores the dwell; a START before the window or now; a KEEP has nothing to change", () => {
  const forced = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 120, socPct: 50, ceilings: [maxChargePowerCeiling(8000, 4000)], inForce: { setpointW: 8000, lastChangeAtMin: 100, changesUsed: 1 } });
  assert.equal(forced.now.change, "DECREASE");
  const line = forced.needed[1] as string;
  assert.match(line, /lowering the charge slot power to 4000 W, the safe ceiling: a forced decrease, whatever the dwell and the change budget say/);
  assert.doesNotMatch(line, /before the window|after 60 min/);
  assert.match(plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: -30, drainBoundW: 0 }).needed[1] as string, /slot power set to \d+ W before the window/);
  assert.match(plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 30 }).needed[1] as string, /slot power set to \d+ W now/);
  assert.match(plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 30, inForce: { setpointW: 6000, lastChangeAtMin: 20, changesUsed: 0 } }).needed[1] as string, /^Nothing to change on the guarded TOU editor now: the charge slot power stays at 6000 W/);
  assert.match(plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } }).needed[1] as string, /changing the charge slot power to \d+ W now/);
  assert.match(plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 100, socPct: 40, inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } }).needed[1] as string, /lease in force keeps 6000 W/);
});

// ---- the third independent review (round 3, tip 8999cdf: 1 BLOCKER, 2 MAJOR, 7 MINOR): each finding pinned by its reproduction and a by-hand value -----------
// The reviewer's inputs are used as given; each test says what the earlier source answered.
const worlds = (p: GentleNightPlan) => [band(p).pessimistic, band(p).expected, band(p).optimistic, band(p).pessimisticHeld];

test("round 3 F5: a world that starts at or above the target has reached it NOW: no finish lies before now or before the window opens (by hand)", () => {
  // the review's case: reading 99.4, target 99.6, minute 10. The optimistic world starts half a point above the reading, at 99.9, above the target: it has
  // finished NOW, at 10 (the earlier source extrapolated the crossing backwards: 4.25, before now)
  const a = plan({ targetSocPct: 99.6, elapsedMin: 10, socPct: 99.4, socAgeMin: 0, actuatorProfile: "FREE_POWER_LEASE" });
  assert.equal(band(a).optimistic.finishMin, 10);
  assert.equal(band(a).optimistic.reachedByDeadline, true);
  assert.ok((band(a).expected.finishMin as number) > 10 && (band(a).pessimistic.finishMin as number) > 10, "the other worlds are not there yet");
  assert.ok((a.expectedFinish as NonNullable<typeof a.expectedFinish>).inMin > 0);
  // before the window opens nothing charges: the window start is the earliest finish (the review's pre-window case gave -14.65)
  const pre = plan({ targetSocPct: 99.6, elapsedMin: -60, drainBoundW: 0, socPct: 99.3, socAgeMin: 0 });
  assert.ok(pre.codes.includes("BEFORE_WINDOW"));
  assert.equal(band(pre).optimistic.finishMin, 0);
  // a seeded sweep with the reading within 1.2 points below the target, before, at and after the window opens and the deadline, on every path: no world finishes before now
  const r = rng(305);
  const profiles = ["UNCONSTRAINED", "FREE_POWER_LEASE", "TOU_SLOT_EDITOR", "RATE_CONTROLLER_PROPOSED"] as const;
  let nearTarget = 0;
  for (let i = 0; i < 600; i++) {
    const targetSocPct = 85 + Math.floor(r() * 16);
    const socPct = Math.round((targetSocPct - r() * 1.2) * 100) / 100;
    const elapsedMin = Math.floor(r() * 330) - 60;
    const p = plan({ targetSocPct, socPct, elapsedMin, socAgeMin: Math.floor(r() * 3), drainBoundW: 0, actuatorProfile: profiles[Math.floor(r() * 4)] as (typeof profiles)[number] });
    if (p.band === null) continue;
    nearTarget++;
    for (const w of worlds(p)) assert.ok(w.finishMin === null || w.finishMin >= Math.max(elapsedMin, 0) - 1e-9, "a finish before now: " + w.finishMin + " at " + elapsedMin + " " + JSON.stringify([targetSocPct, socPct]));
  }
  assert.ok(nearTarget > 500, "planned " + nearTarget);
});

test("round 3 F6: the SOC at the deadline is FLOORED to a tenth, so it never shows the target for a world that has not reached it; after the deadline it is the SOC now, never above the target (by hand)", () => {
  // the review's TOU case: 4100 W from 79.083 (2 min old, drain bound 22230 W: 1.25 points), target 90.5, deadline 194. Pessimistic start 77.83 - 1.0 = 76.83,
  // 3.69 kW / 60 / (64.93 x 1.06 / 0.97 / 100 = 0.70954 kWh per point) = 0.08668 points a minute: the knee 90 at minute 151.9, the cliff minute 0.04876 points,
  // the tail 0.010835 points a minute for the 41.1 min left: 90.494 at the deadline, 0.006 short of the target: shown 90.4 (90.5 rounded, with "not reached")
  const t = plan({ actuatorProfile: "TOU_SLOT_EDITOR", chargeWindow: { startMin: 174, endMin: 428 }, elapsedMin: 0, socPct: 79.083, socAgeMin: 2, capacityKwh: 64.93, ceilings: [maxChargePowerCeiling(8000, 4100)], drainBoundW: 22230, targetSocPct: 90.5 });
  const start = 79.083 - (22.23 * 2) / 60 / ((64.93 * 0.94) / 1.03 / 100) - 1.0;
  const perMin = (4.1 * 0.9) / 60 / ((64.93 * 1.06) / 0.97 / 100);
  const exact = 90 + ((1 + 0.125) / 2) * perMin + 0.125 * perMin * (194 - (90 - start) / perMin - 1);
  assert.ok(exact > 90.45 && exact < 90.5, "the by-hand value " + exact);
  assert.equal(band(t).pessimisticHeld.reachedByDeadline, false);
  assert.equal(band(t).pessimisticHeld.socAtDeadlinePct, Math.floor(exact * 10) / 10);
  assert.equal(band(t).pessimisticHeld.socAtDeadlinePct, 90.4);
  // the invariant over a sweep of capacities around it: a world that has reached the target shows it exactly, one that has not shows less than it, in whole tenths
  let near = 0;
  for (let i = 0; i < 400; i++) {
    const p = plan({ actuatorProfile: "TOU_SLOT_EDITOR", chargeWindow: { startMin: 174, endMin: 428 }, socPct: 79.083, socAgeMin: 2, capacityKwh: 64.5 + i * 0.002, ceilings: [maxChargePowerCeiling(8000, 4100)], drainBoundW: 22230, targetSocPct: 90.5 });
    for (const w of worlds(p)) {
      if (w.reachedByDeadline) assert.equal(w.socAtDeadlinePct, 90.5);
      else {
        assert.ok(w.socAtDeadlinePct < 90.5, "shows the target while not reached: " + w.socAtDeadlinePct);
        assert.ok(Math.abs(w.socAtDeadlinePct * 10 - Math.round(w.socAtDeadlinePct * 10)) < 1e-6, "whole tenths: " + w.socAtDeadlinePct);
        if (w.socAtDeadlinePct === 90.4) near++;
      }
    }
  }
  assert.ok(near > 20, "cases within a tenth of the target: " + near);
  // a target that is not a whole tenth is shown as given once it is reached (the earlier rounding showed 90.1 for 90.05)
  const odd = plan({ targetSocPct: 60.05, socPct: 40 });
  assert.equal(band(odd).pessimisticHeld.reachedByDeadline, true);
  assert.equal(band(odd).pessimisticHeld.socAtDeadlinePct, 60.05);
  // after the deadline (window still open) it is the SOC NOW: the optimistic world starts above the target (89.8 + 0.5 = 90.3 against 90) and shows the target, not
  // 90.3; the expected world 89.8, the pessimistic one 88.8; nothing is "reached by the deadline"
  const late = plan({ elapsedMin: 250, socPct: 89.8, targetSocPct: 90, inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.ok(late.codes.includes("DEADLINE_PASSED_WINDOW_OPEN"));
  assert.deepEqual(worlds(late).map((w) => w.socAtDeadlinePct), [88.8, 89.8, 90, 88.8]);
  assert.deepEqual(worlds(late).map((w) => w.reachedByDeadline), [false, false, false, false]);
  // and over a sweep after the deadline, no world is above the target and none is reached by it
  const r = rng(306);
  for (let i = 0; i < 300; i++) {
    const targetSocPct = 80 + Math.floor(r() * 21);
    const p = plan({ targetSocPct, socPct: Math.round((targetSocPct - r() * 3) * 10) / 10, elapsedMin: 241 + Math.floor(r() * 50), inForce: { setpointW: 500 + 100 * Math.floor(r() * 76), lastChangeAtMin: 0, changesUsed: 0 } });
    if (p.band === null) continue;
    for (const w of worlds(p)) {
      assert.ok(w.socAtDeadlinePct <= targetSocPct, "above the target after the deadline: " + w.socAtDeadlinePct + " against " + targetSocPct);
      assert.equal(w.reachedByDeadline, false);
    }
  }
});

test("round 3 F1 (BLOCKER): a rate in force that was SET after the reading leaves the minutes from the reading to it idle: the drain counts, and the review's case is no longer OK (by hand)", () => {
  // the review's case: reading 40 taken at minute 0.5 (age 14.5 at minute 15), the lease STARTed at minute 14 at 2000 W, the house drawing up to 3000 W from the
  // battery in between: 13.5 idle minutes = 0.675 kWh = 2.333 points of the most points per kWh. The earlier source counted none (OK, margin 5.6); the truth at the
  // envelope's corner (shown 40 = clean 39.0) reaches 58 at minute 255.9, after the deadline 240
  const f1 = { actuatorProfile: "FREE_POWER_LEASE", targetSocPct: 58, socPct: 40, drainBoundW: 3000 } as const;
  const p = plan({ ...f1, elapsedMin: 15, socAgeMin: 14.5, inForce: { setpointW: 2000, lastChangeAtMin: 14, changesUsed: 0 } });
  const drained = (3 * 13.5) / 60 / OPT;
  assert.equal(p.assumptions?.idleSinceReadingMin, 13.5);
  near(p.assumptions?.socAtPlanStartPct, 40 - drained, 0.006, "the SOC the plan starts from");
  // pessimistic start 40 - 2.333 - 1.0, 2000 W x 0.9 = 1.8 kW held from minute 15
  near(band(p).pessimisticHeld.finishMin, 15 + (((58 - (40 - drained - 1)) * PK) / 1.8) * 60, 0.1, "the held finish");
  assert.equal(p.status, "TARGET_AT_RISK");
  assert.equal(band(p).pessimisticHeld.reachedByDeadline, false);
  assert.ok((p.marginMin as number) < -20 && (p.marginMin as number) > -22, "the margin " + p.marginMin);
  // without a bound the 13.5 minutes (more than the 2 that may go uncounted) are refused, never guessed
  assert.deepEqual(plan({ ...f1, drainBoundW: undefined, elapsedMin: 15, socAgeMin: 14.5, inForce: { setpointW: 2000, lastChangeAtMin: 14, changesUsed: 0 } }).codes, ["DRAIN_UNKNOWN_AGED_READING"]);
  // the minutes are those from the reading to the rate being set, no more: set BEFORE the reading (minute 0) nothing is idle; the limit of 2 is inclusive
  const idle = (lastChangeAtMin: number | null): GentleNightPlan => plan({ ...f1, drainBoundW: undefined, elapsedMin: 15, socAgeMin: 5, inForce: { setpointW: 2000, lastChangeAtMin, changesUsed: 0 } });
  for (const before of [0, 9.99, 10, null]) {
    assert.equal(idle(before).assumptions?.idleSinceReadingMin, 0, String(before));
    assert.ok(!idle(before).codes.includes("DRAIN_NOT_COUNTED"), String(before));
  }
  assert.equal(idle(11.5).assumptions?.idleSinceReadingMin, 1.5);
  assert.ok(idle(11.5).codes.includes("DRAIN_NOT_COUNTED"));
  assert.equal(idle(12).assumptions?.idleSinceReadingMin, 2);
  assert.ok(idle(12).codes.includes("DRAIN_NOT_COUNTED"), "exactly 2 minutes may go uncounted");
  assert.deepEqual(idle(12.5).codes, ["DRAIN_UNKNOWN_AGED_READING"]);
  // both parts count when the reading was taken before the window opened: reading at minute -3 (age 15 at minute 12), the rate set at minute 10: 3 + 10 minutes
  const both = plan({ ...f1, elapsedMin: 12, socAgeMin: 15, inForce: { setpointW: 2000, lastChangeAtMin: 10, changesUsed: 0 } });
  assert.equal(both.assumptions?.idleSinceReadingMin, 13);
  // a rate set before the window opens (minute -20) with the reading taken at -25: only the 25 minutes before the window, as before
  assert.equal(plan({ ...f1, elapsedMin: -10, socAgeMin: 15, inForce: { setpointW: 2000, lastChangeAtMin: -20, changesUsed: 0 } }).assumptions?.idleSinceReadingMin, 25);
  // a START the planner itself recommended stays OK once it is applied (the same reading asked again a minute later): 2200 W at minute 13.9 (13.4 idle minutes), then
  // {2200 W, set at 13.9} at minute 15 with the same reading: the same start SOC, 1.2 minutes of margin
  const start = plan({ ...f1, elapsedMin: 13.9, socAgeMin: 13.4 });
  assert.equal(start.now.change, "START");
  assert.equal(start.now.setpointW, 2200);
  assert.equal(start.status, "OK");
  const applied = plan({ ...f1, elapsedMin: 15, socAgeMin: 14.5, inForce: { setpointW: 2200, lastChangeAtMin: 13.9, changesUsed: 0 } });
  assert.equal(applied.status, "OK");
  assert.equal(applied.assumptions?.socAtPlanStartPct, start.assumptions?.socAtPlanStartPct);
  near(applied.marginMin, 240 - (15 + (((58 - (40 - (3 * 13.4) / 60 / OPT - 1)) * PK) / 1.98) * 60), 0.1, "the applied START's margin");
});

test("round 3 F7: a fall against the previous reading is allowed up to the drain bound over the minutes in which nothing charged (before the window, or with nothing in force); never with a rate in force (by hand)", () => {
  // the review's case: 50 % at minute -180, 44 % at minute -121 (age 1 at -120), a drain bound of 2500 W given: 59 minutes, 2.458 kWh = 8.497 points of the most points
  // per kWh, plus the tolerance 3: a fall of up to 11.497 is plausible (refused before: 6 > 3)
  const pre = (socPct: number, prevPct: number, over: Partial<GentleNightInput> = {}): GentleNightPlan => plan({ elapsedMin: -120, socPct, socAgeMin: 1, drainBoundW: 2500, previousSoc: { socPct: prevPct, elapsedMin: -180 }, ...over });
  assert.ok(!pre(44, 50).codes.includes("SOC_IMPLAUSIBLE"));
  assert.equal(pre(44, 50).status, "OK");
  assert.ok(!pre(44, 55.4).codes.includes("SOC_IMPLAUSIBLE"), "a fall of 11.4 <= 11.497");
  assert.deepEqual(pre(44, 55.6).codes, ["SOC_IMPLAUSIBLE"]);
  // no bound given: the tolerance alone, as before (and the missing bound would refuse the plan anyway)
  assert.deepEqual(plan({ elapsedMin: -120, socPct: 44, socAgeMin: 1, previousSoc: { socPct: 50, elapsedMin: -180 } }).codes, ["SOC_IMPLAUSIBLE"]);
  assert.deepEqual(pre(44, 50, { drainBoundW: 0 }).codes, ["SOC_IMPLAUSIBLE"], "a bound of 0 W excuses nothing");
  // inside the window with nothing in force: previous 50 at minute 40, 4.5 / 4.2 now at 59 (age 1): 19 idle minutes = 2.736 points, so 5.736 allowed
  const open = (socPct: number, over: Partial<GentleNightInput> = {}): GentleNightPlan => plan({ elapsedMin: 60, socPct, socAgeMin: 1, drainBoundW: 2500, previousSoc: { socPct: 50, elapsedMin: 40 }, ...over });
  assert.ok(!open(44.5).codes.includes("SOC_IMPLAUSIBLE"), "a fall of 5.5 <= 5.736");
  assert.deepEqual(open(44.2).codes, ["SOC_IMPLAUSIBLE"], "a fall of 5.8 > 5.736");
  // a rate in force since before the previous reading charges: no minute is idle, a fall of 6 is refused whatever the bound
  assert.deepEqual(open(44, { inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 } }).codes, ["SOC_IMPLAUSIBLE"]);
  // a rate set at minute 50 (after the previous reading at 40, before the reading at 59): the minutes 40 to 50 are idle: 10 minutes = 1.44 points, so 4.44 allowed
  assert.ok(!open(45.7, { inForce: { setpointW: 3000, lastChangeAtMin: 50, changesUsed: 0 } }).codes.includes("SOC_IMPLAUSIBLE"), "a fall of 4.3 <= 4.44");
  assert.deepEqual(open(45.4, { inForce: { setpointW: 3000, lastChangeAtMin: 50, changesUsed: 0 } }).codes, ["SOC_IMPLAUSIBLE"], "a fall of 4.6 > 4.44");
  // a rise is judged as before (the allowance is for falls only)
  assert.deepEqual(plan({ socPct: 40, elapsedMin: 6, previousSoc: { socPct: 20, elapsedMin: 0 }, drainBoundW: 3000 }).codes, ["SOC_IMPLAUSIBLE"]);
});

test("round 3 F2 (MAJOR): a rate in force that an ordinary change set INSIDE the window while the knee may already have been passed has an unknown knee rate: the tail is taken at the lowest setpoint, so OK needs the deadline to hold even then (by hand)", () => {
  // the review's case: the owner raised 2000 W to 8000 W at minute 25, AFTER the knee was crossed at 2000 W; reading 91 at minute 30, target 95, window 300 minutes,
  // deadline 240. The earlier source anchored the tail at the new 8000 W (900 W of tail, finish 145.5, margin 94.5: OK) while the battery stays on 0.125 x 2000 x 0.9 =
  // 225 W: 5 points x 0.346412 kWh = 7.7 hours. The record cannot tell the earlier rate, so the worst case is the lowest setpoint, 500 W: 56.25 W of tail
  const win = { chargeWindow: { startMin: 600, endMin: 900 }, bufferMin: 60, elapsedMin: 30, socPct: 91, socAgeMin: 0, targetSocPct: 95, actuatorProfile: "TOU_SLOT_EDITOR" } as const;
  const raised = plan({ ...win, inForce: { setpointW: 8000, lastChangeAtMin: 25, changesUsed: 1 } });
  assert.equal(raised.status, "TARGET_AT_RISK");
  assert.ok(raised.codes.includes("KNEE_RATE_UNKNOWN"));
  assert.equal(raised.now.change, "KEEP");
  assert.equal(raised.now.setpointW, 8000);
  assert.equal(band(raised).pessimisticHeld.finishMin, null, "5 points at 56.25 W do not finish in the window");
  assert.equal(raised.marginMin, null);
  assert.equal(raised.now.neededMeetsDeadline, false, "no rate makes it when the tail is anchored at the lowest setpoint");
  assert.equal(band(raised).expected.reachedByDeadline, true, "the expected world is anchored at the rate in force and does");
  // the same battery with 2000 W still in force is already TARGET_AT_RISK (the truth)
  assert.equal(plan({ ...win, inForce: { setpointW: 2000, lastChangeAtMin: -60, changesUsed: 0 } }).status, "TARGET_AT_RISK");
  // what does NOT make the knee rate unknown: a START (changesUsed 0: nothing charged before it), a change before the window opened (nothing charged before it, so
  // the rate in force was the one at the knee), the window start itself, a target at or below the pessimistic knee, a call before the window
  const okAt = (inForce: GentleNightInput["inForce"], over: Partial<GentleNightInput> = {}): GentleNightPlan => plan({ ...win, inForce, ...over });
  for (const c of [okAt({ setpointW: 8000, lastChangeAtMin: 25, changesUsed: 0 }), okAt({ setpointW: 8000, lastChangeAtMin: -30, changesUsed: 1 }), okAt({ setpointW: 8000, lastChangeAtMin: 0, changesUsed: 1 }),
    okAt({ setpointW: 8000, lastChangeAtMin: 25, changesUsed: 1 }, { targetSocPct: 90 })]) {
    assert.ok(!c.codes.includes("KNEE_RATE_UNKNOWN"), c.codes.join(","));
  }
  assert.equal(okAt({ setpointW: 8000, lastChangeAtMin: 25, changesUsed: 0 }).status, "OK", "a START is anchored at its own rate, margin 94.5");
  assert.equal(okAt({ setpointW: 8000, lastChangeAtMin: -30, changesUsed: 1 }).status, "OK");
  const beforeWindow = okAt({ setpointW: 8000, lastChangeAtMin: -40, changesUsed: 1 }, { elapsedMin: -30, drainBoundW: 0 });
  assert.notEqual(beforeWindow.status, "INPUTS_UNUSABLE", "a planned call: " + beforeWindow.codes.join(","));
  assert.ok(!beforeWindow.codes.includes("KNEE_RATE_UNKNOWN"));
  // the window start is the edge: set at 0 is not inside the window, set at 0.5 is; a time that is not given (null) with a counted change cannot be placed, so it counts
  assert.ok(!okAt({ setpointW: 8000, lastChangeAtMin: 0, changesUsed: 1 }).codes.includes("KNEE_RATE_UNKNOWN"));
  assert.ok(okAt({ setpointW: 8000, lastChangeAtMin: 0.5, changesUsed: 1 }).codes.includes("KNEE_RATE_UNKNOWN"));
  assert.ok(okAt({ setpointW: 8000, lastChangeAtMin: null, changesUsed: 1 }).codes.includes("KNEE_RATE_UNKNOWN"));
  // the knee must MAY be passed when the rate was set: a change made AFTER the reading is judged from the reading plus the charge possible up to it: reading R at minute
  // 25 (age 5 at minute 30), set at minute 28: 3 minutes at the firmware bound, 3 x 8000 x 1.1 / 60000 / 0.289301 = 1.521 points, so the estimate 1.0 + 1.521 above the
  // reading reaches 90 from 87.479: 87.4 is surely ahead (no unknown), 87.5 may be past
  const after = (socPct: number): GentleNightPlan => plan({ ...win, socPct, socAgeMin: 5, drainBoundW: 0, inForce: { setpointW: 8000, lastChangeAtMin: 28, changesUsed: 1 } });
  assert.ok(!after(87.4).codes.includes("KNEE_RATE_UNKNOWN"));
  assert.ok(after(87.5).codes.includes("KNEE_RATE_UNKNOWN"));
  // a change made BEFORE the reading is judged from the reading alone (the position at the change is at most the position at the reading): 88.9 + 1.0 < 90, 89 + 1.0 = 90
  const before = (socPct: number): GentleNightPlan => plan({ ...win, socPct, socAgeMin: 5, drainBoundW: 0, inForce: { setpointW: 8000, lastChangeAtMin: 10, changesUsed: 1 } });
  assert.ok(!before(88.9).codes.includes("KNEE_RATE_UNKNOWN"));
  assert.ok(before(89).codes.includes("KNEE_RATE_UNKNOWN"));
  // OK is still possible when the deadline holds even at the worst case: 1000 minutes, no buffer, target 91.5 from 91 (pessimistic start 90.0, on the knee): 1.5 points x
  // 0.346412 = 0.5196 kWh at the 56.25 W tail = 554.3 minutes after minute 30, finish 584.3 <= 1000. At the 8000 W in force (900 W tail) it would be 34.6 minutes
  const roomy = { ...win, chargeWindow: { startMin: 100, endMin: 1100 }, bufferMin: 0, targetSocPct: 91.5 } as const;
  const wide = plan({ ...roomy, inForce: { setpointW: 8000, lastChangeAtMin: 25, changesUsed: 1 } });
  assert.ok(wide.codes.includes("KNEE_RATE_UNKNOWN"));
  assert.equal(wide.status, "OK");
  near(band(wide).pessimisticHeld.finishMin, 30 + ((1.5 * PK) / 0.05625) * 60, 0.2, "at the lowest tail");
  near(band(plan({ ...roomy, inForce: { setpointW: 8000, lastChangeAtMin: 25, changesUsed: 0 } })).pessimisticHeld.finishMin, 30 + ((1.5 * PK) / 0.9) * 60, 0.2, "at the rate in force (a START)");
});

test("round 3 F3 (MAJOR): a rate in force above a known ceiling is compared whenever it is a finite number above 0 W, whatever the bookkeeping fields, the parameters or the path name say: a STOP on a path that cannot lower it, never 'the fallback holds whatever is in force'", () => {
  // the review's cases: a lease of 8000 W against the 6000 W owner limit, the record's bookkeeping malformed (it answered INPUT_INVALID with the fallback line)
  type ForceT = NonNullable<GentleNightInput["inForce"]>;
  const lease = (inForce: unknown, over: Partial<GentleNightInput> = {}): GentleNightPlan => plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: inForce as ForceT, ...over });
  const stops = (p: GentleNightPlan, first: NightCode, what: string): void => {
    assert.equal(p.status, "STOP_RECOMMENDED", what + ": " + p.codes.join(","));
    assert.equal(p.stopRecommended, true, what);
    assert.equal(p.now.change, "STOP", what);
    assert.deepEqual(p.codes, [first, "FORCED_BELOW_CEILING", "ACTUATOR_FIXED_RATE"], what);
    assert.equal(p.now.ceilingW, 6000, what);
    assert.match(p.needed.join(" "), /Stop the charge on this path: the rate in force \(8000 W\) is above the safe ceiling \(6000 W/, what);
    assert.doesNotMatch(p.needed.join(" "), /fallback holds/, what);
  };
  const malformed: Array<[string, unknown]> = [
    ["changesUsed missing", { setpointW: 8000, lastChangeAtMin: 0 }], ["changesUsed 0.5", { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0.5 }], ["changesUsed negative", { setpointW: 8000, lastChangeAtMin: 0, changesUsed: -1 }],
    ["changesUsed a string", { setpointW: 8000, lastChangeAtMin: 0, changesUsed: "0" }], ["lastChangeAtMin missing", { setpointW: 8000, changesUsed: 0 }], ["lastChangeAtMin NaN", { setpointW: 8000, lastChangeAtMin: NaN, changesUsed: 0 }],
    ["lastChangeAtMin a string", { setpointW: 8000, lastChangeAtMin: "0", changesUsed: 0 }], ["both missing", { setpointW: 8000 }],
  ];
  for (const [what, rec] of malformed) stops(lease(rec), "INPUT_INVALID", what);
  // the grid case: a 6000 W lease against a 3000 W import limit with 2500 W of fresh demand (the headroom is 0 W: below the lowest setpoint)
  const grid = lease({ setpointW: 6000, lastChangeAtMin: 0 }, { ceilings: [maxChargePowerCeiling(8000, 8000)], household: { gridImportLimitW: 3000, demandPeakW: 2500, demandAgeMin: 1 } });
  assert.equal(grid.status, "STOP_RECOMMENDED");
  assert.deepEqual(grid.codes, ["INPUT_INVALID", "FORCED_BELOW_CEILING", "ACTUATOR_FIXED_RATE", "HEADROOM_BELOW_MIN"]);
  assert.equal(grid.now.ceilingName, "grid_headroom");
  // the earlier exclusions: invalid parameters and an unknown path (taken as one that cannot lower the rate); the valid parameters are kept and the invalid ones fall back to their defaults
  stops(lease({ setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 }, { params: { replanMin: 20 } }), "PARAMS_INVALID", "an invalid parameter");
  stops(lease({ setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 }, { actuatorProfile: "FREE_POWER_LEAS" as never }), "PROFILE_INVALID", "a profile typo");
  stops(lease({ setpointW: 8000 }, { actuatorProfile: "MAGIC" as never }), "PROFILE_INVALID", "an unknown path and a malformed record at once");
  assert.equal(lease({ setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 }, { actuatorProfile: "MAGIC" as never }).profile, null, "an unknown path has no profile report");
  const kept = lease({ setpointW: 5500, lastChangeAtMin: 0, changesUsed: 0 }, { ceilings: [maxChargePowerCeiling(8000, 8000)], params: { hardMaxW: 5000, replanMin: 20 } });
  assert.equal(kept.status, "STOP_RECOMMENDED", "the valid hardMaxW 5000 is kept");
  assert.equal(kept.now.ceilingW, 5000);
  assert.equal(kept.now.ceilingName, "firmware_setpoint_bound");
  // on a path that CAN lower the rate the refusal stays and says it must come down (never the fallback line), also for a malformed record and invalid parameters
  for (const over of [{}, { params: { replanMin: 20 } }]) {
    const tou = lease({ setpointW: 8000, changesUsed: 0.5 }, { actuatorProfile: "TOU_SLOT_EDITOR", ...over });
    assert.equal(tou.status, "INPUTS_UNUSABLE");
    assert.equal(tou.stopRecommended, false);
    assert.ok(tou.codes.includes("FORCED_BELOW_CEILING") && !tou.codes.includes("ACTUATOR_FIXED_RATE"), tou.codes.join(","));
    assert.match(tou.needed.join(" "), /must come down to at most 6000 W whatever else is unknown/);
    assert.doesNotMatch(tou.needed.join(" "), /fallback holds/);
  }
  // no breach, no STOP: a malformed record at the ceiling, or no usable rate at all (a string, a negative number, NaN, a 0 W rate that means not charging), keeps the plain refusal
  for (const rec of [{ setpointW: 6000 }, { setpointW: "8000", lastChangeAtMin: 0, changesUsed: 0 }, { setpointW: -8000, lastChangeAtMin: 0, changesUsed: 0 }, { setpointW: NaN }, { setpointW: Infinity }, { setpointW: 0 }, null]) {
    const p = lease(rec, { socPct: null });
    assert.equal(p.status, "INPUTS_UNUSABLE", JSON.stringify(rec));
    assert.equal(p.stopRecommended, false, JSON.stringify(rec));
    assert.match(p.needed.join(" "), /the fallback holds whatever is in force/, JSON.stringify(rec));
  }
  // with no named ceiling the only known one is the firmware bound (8000 W): 9000 W in force is above it (a STOP), 6100 W is not (nothing known is breached: the plain refusal)
  const none = lease({ setpointW: 9000, changesUsed: 0.5 }, { ceilings: [] });
  assert.equal(none.status, "STOP_RECOMMENDED");
  assert.equal(none.now.ceilingW, 8000);
  assert.equal(none.now.ceilingName, "firmware_setpoint_bound");
  assert.deepEqual(none.codes, ["INPUT_INVALID", "FORCED_BELOW_CEILING", "ACTUATOR_FIXED_RATE"]);
  assert.match(lease({ setpointW: 6100, changesUsed: 0.5 }, { ceilings: [] }).needed.join(" "), /the fallback holds whatever is in force/);
  // a seeded sweep over every refusal kind, every path (and an unknown one), a sound and a malformed record, rates above 6000 W: the plan is never the fallback line, and on a
  // path that cannot lower the rate (the lease, an unknown one) it is a STOP
  const r = rng(307);
  const refusals: Array<Partial<GentleNightInput>> = [{}, { targetSocPct: 5 }, { bufferMin: 7 }, { chargeWindow: null as never }, { clockDay: null as never }, { elapsedMin: NaN }, { socPct: null }, { socAgeMin: 30 }, { socPct: 101 },
    { capacityKwh: 0 }, { params: { setpointOvershoot: 2 } }, { drainBoundW: 5, preWindowDrainW: 9 }, { elapsedMin: -30 }, { socPct: 99 }, { household: { gridImportLimitW: -5 } }];
  const paths = ["FREE_POWER_LEASE", "TOU_SLOT_EDITOR", "UNCONSTRAINED", "RATE_CONTROLLER_PROPOSED", "NO_SUCH_PATH"] as const;
  const records: unknown[] = [{ setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 }, { setpointW: 6100 }, { setpointW: 9000, lastChangeAtMin: "x", changesUsed: 0 }, { setpointW: 7000, lastChangeAtMin: 0, changesUsed: 1.5 }];
  let stopped = 0;
  for (let i = 0; i < 400; i++) {
    const path = paths[Math.floor(r() * paths.length)] as (typeof paths)[number];
    const over = refusals[Math.floor(r() * refusals.length)] as Partial<GentleNightInput>;
    const p = plan({ elapsedMin: 60, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], ...over, actuatorProfile: path as never, inForce: records[Math.floor(r() * records.length)] as ForceT });
    assert.doesNotMatch(p.needed.join(" "), /fallback holds/, path + " " + JSON.stringify(over) + " " + p.codes.join(","));
    if (path === "FREE_POWER_LEASE" || path === "NO_SUCH_PATH") {
      assert.equal(p.status, "STOP_RECOMMENDED", path + " " + JSON.stringify(over) + " " + p.codes.join(","));
      stopped++;
    }
  }
  assert.ok(stopped > 100, "sweep stops: " + stopped);
});

test("round 3 F9: the planner never throws for a ceiling name that cannot be converted to text, nor for a profile name or any junk in any field (prototype-less objects, symbols, bigints, functions, proxies, objects whose conversion throws)", () => {
  const bare = Object.create(null) as never;
  // the review's case: a ceiling name with no prototype threw 'Cannot convert object to primitive value', with or without a rate in force
  for (const inForce of [undefined, { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 }]) {
    const p = plan({ elapsedMin: 60, socPct: 40, ceilings: [{ name: bare, watts: 5000 }], inForce });
    assert.equal(p.now.ceilingW, 5000);
    assert.equal(p.now.ceilingName, "unnamed");
    assert.equal(p.status, inForce === undefined ? "TARGET_AT_RISK" : "STOP_RECOMMENDED");
  }
  // a name is used only when it is a string; the real one is unchanged
  assert.equal(plan({ ceilings: [{ name: 7 as never, watts: 5000 }, maxChargePowerCeiling(8000, 6000)] }).now.ceilingName, "unnamed");
  assert.equal(plan({ ceilings: [{ name: ["a"] as never, watts: 5000 }] }).now.ceilingName, "unnamed");
  assert.equal(plan({ ceilings: [{ name: "grid_charge_limit", watts: 5000 }] }).now.ceilingName, "grid_charge_limit");
  assert.equal(plan().now.ceilingName, "max_charge_power_effective");
  // the controller's own helpers (the night planner uses effectiveCeiling; planGentle uses both)
  assert.deepEqual(smallestKnownCeiling([{ name: bare, watts: 5000 }, { name: "b", watts: 6000 }]), { watts: 5000, name: "unnamed" });
  assert.deepEqual(effectiveCeiling([{ name: bare, watts: 5000 }, { name: bare, watts: 3000, ageMin: 999 }], 60), { best: { watts: 3000, name: "unnamed" }, staleNames: ["unnamed"], staleCaps: true });
  assert.deepEqual(smallestKnownCeiling([{ name: "owner", watts: 5000 }]), { watts: 5000, name: "owner" });
  // a profile that is an object with no prototype, a symbol, or an object whose conversion throws is an unknown path, not a throw
  const thrower = { toString() { throw new Error("toString"); }, valueOf() { throw new Error("valueOf"); } };
  for (const profile of [bare, Symbol("p"), thrower, 7, []]) assert.deepEqual(plan({ actuatorProfile: profile as never }).codes, ["PROFILE_INVALID"]);
  // junk in every field and every record field, the throwing kinds included: never a throw, never an actuation, always a code from the closed list
  const r = rng(308);
  const junk: unknown[] = [bare, Symbol("s"), 10n, () => 1, new Proxy({}, {}), [bare], thrower, [thrower], { name: thrower, watts: 5000 }, NaN, Infinity, -1, "x", null, undefined, true, [], {}];
  const full: Record<string, unknown> = {
    targetSocPct: 80, chargeWindow: { startMin: 30, endMin: 330 }, clockDay: ORD, elapsedMin: 60, socPct: 40, socAgeMin: 1, capacityKwh: 31.7, ceilings: [maxChargePowerCeiling(8000, 6000)],
    household: { gridImportLimitW: 9000, demandPeakW: 1000, demandAgeMin: 1 }, inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 }, actuatorProfile: "TOU_SLOT_EDITOR",
    previousSoc: { socPct: 39, elapsedMin: 50 }, drainBoundW: 100, params: { dropMin: 5 }, learnedCapacityKwh: 30,
  };
  let planned = 0;
  for (let i = 0; i < 1500; i++) {
    const o: Record<string, unknown> = JSON.parse(JSON.stringify(full));
    const keys = Object.keys(o);
    const k = keys[Math.floor(r() * keys.length)] as string;
    const pick = junk[Math.floor(r() * junk.length)];
    const v = o[k];
    if (r() < 0.5 || v === null || typeof v !== "object") o[k] = pick;
    else if (Array.isArray(v)) o[k] = [pick, ...v];
    else {
      const kk = Object.keys(v as object);
      (v as Record<string, unknown>)[kk[Math.floor(r() * kk.length)] as string] = pick;
    }
    let p: GentleNightPlan | null = null;
    try {
      p = planGentleNight(o as unknown as GentleNightInput);
    } catch (e) {
      assert.fail("threw for " + k + ": " + String(e));
    }
    assert.equal(p.actuationSupported, false);
    for (const c of p.codes) assert.ok((NIGHT_CODES as readonly string[]).includes(c), c);
    planned++;
  }
  assert.equal(planned, 1500);
});

test("round 3 F4: UNREACHABLE means not even the highest safe rate the path can still apply reaches the target inside the window; a rate that only the dwell holds low is TARGET_AT_RISK (by hand)", () => {
  // the review's case: UNCONSTRAINED, window 303 to 541 (238 minutes), buffer 90, minute 0.5, reading 88.277 (2 min old), owner limit 5000 W, 500 W set at minute -0.5
  // (the dwell holds it for 30 minutes), target 95. The 500 W held never gets there, but 5000 W applied now finishes: the pessimistic start 87.277 reaches the knee 90 on the
  // plateau (4.5 kW = 0.21651 points a minute) in 12.58 minutes, the cliff minute gives 0.1218 points, then 4.878 points on the tail 0.125 x 4.5 kW = 0.5625 kW take
  // 180.25 minutes: minute 194.3, before the window end (238), after the deadline (148): at risk, not unreachable
  const rc = { actuatorProfile: "UNCONSTRAINED", targetSocPct: 95, bufferMin: 90, chargeWindow: { startMin: 303, endMin: 541 }, elapsedMin: 0.5, socPct: 88.27706020426044, socAgeMin: 2.0001, inForce: { setpointW: 500, lastChangeAtMin: -0.5, changesUsed: 0 } } as const;
  const owner = (watts: number): GentleNightInput["ceilings"] => [{ name: "max_charge_power_effective", watts }];
  const p = plan({ ...rc, ceilings: owner(5000) });
  const perMin = 4.5 / 60 / PK;
  const atTop = 0.5 + (90 - (88.27706020426044 - 1.0)) / perMin + 1 + (5 - ((1 + 0.125) / 2) * perMin) / (0.125 * perMin);
  assert.ok(atTop > 148 && atTop < 238, "by hand " + atTop);
  assert.equal(p.status, "TARGET_AT_RISK");
  assert.equal(p.now.change, "KEEP");
  assert.equal(p.now.setpointW, 500);
  assert.ok(p.codes.includes("HELD_DWELL") && p.codes.includes("PESSIMISTIC_MISSES_DEADLINE"), p.codes.join(","));
  assert.equal(band(p).pessimisticHeld.finishMin, null, "the 500 W held never gets there");
  // the same battery with the owner limit lowered to 1500 W: the highest safe rate is then 1500 W (0.065 points a minute, then a 168 W tail: about 10 hours), so UNREACHABLE
  assert.equal(plan({ ...rc, ceilings: owner(1500) }).status, "UNREACHABLE");
  // the editor's dwell (60 minutes) holds 2000 W set at minute 50: 8000 W would finish at 218 of 300 (14.2 kWh at 7.2 kW), 2000 W held takes 473 minutes
  const dwell = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 50, changesUsed: 0 } });
  assert.equal(dwell.status, "TARGET_AT_RISK");
  assert.ok(dwell.codes.includes("HELD_DWELL"));
  // a path that cannot change the rate (the lease) and a used-up change budget cannot apply a higher one: the rate in force held is the answer, UNREACHABLE as before
  assert.equal(plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } }).status, "UNREACHABLE");
  assert.equal(plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 1 } }).status, "UNREACHABLE");
  assert.equal(plan({ actuatorProfile: "UNCONSTRAINED", elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 6 } }).status, "UNREACHABLE");
  // and the same battery with the dwell passed (set at minute 0) is raised now: the raise is the first recommendation, so it is judged held and is OK
  const passed = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 100, socPct: 40, inForce: { setpointW: 2000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(passed.now.change, "INCREASE");
  assert.equal(passed.status, "OK");
});

test("round 3 F4: the band is per-world policy and can come out of order on an adaptive path, but with the rate held the order pessimistic >= expected >= optimistic holds on every flat path (sweep)", () => {
  const r = rng(309);
  const fin = (w: { finishMin: number | null }): number => (w.finishMin === null ? Infinity : w.finishMin);
  let compared = 0;
  for (let i = 0; i < 500; i++) {
    const p = plan({
      actuatorProfile: "FREE_POWER_LEASE", socPct: Math.floor(r() * 950) / 10, targetSocPct: 60 + Math.floor(r() * 41), bufferMin: 5 * Math.floor(r() * 25), elapsedMin: Math.floor(r() * 250), capacityKwh: 15 + r() * 30,
      inForce: { setpointW: 500 + 100 * Math.floor(r() * 76), lastChangeAtMin: 0, changesUsed: 0 },
    });
    if (p.band === null || p.status === "STOP_RECOMMENDED") continue;
    compared++;
    const b = p.band;
    assert.ok(fin(b.pessimistic) >= fin(b.expected) - 1e-9 && fin(b.expected) >= fin(b.optimistic) - 1e-9, JSON.stringify(b));
    assert.ok(b.pessimistic.socAtDeadlinePct <= b.expected.socAtDeadlinePct + 1e-9 && b.expected.socAtDeadlinePct <= b.optimistic.socAtDeadlinePct + 1e-9, JSON.stringify(b));
    assert.deepEqual(b.pessimistic, b.pessimisticHeld, "a flat path: the policy is the held rate");
  }
  assert.ok(compared > 300, "compared " + compared);
});

test("round 3 F8: at or above the target with a lease in force the advice says the lease goes on charging past the target and that stopping it is the owner's choice, not that nothing is to be applied (by hand)", () => {
  // the review's case: the Free Power lease (default path), 3000 W set at minute 0, reading 85 against a target of 80 at minute 60
  const lease = plan({ elapsedMin: 60, socPct: 85, inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(lease.status, "NO_NEED");
  assert.deepEqual(lease.codes, ["AT_TARGET"]);
  const text = lease.needed.join(" ");
  assert.match(text, /3000 W/);
  assert.match(text, /no stop at a target SOC/);
  assert.match(text, /keeps charging past the target/);
  assert.match(text, /the owner's choice/);
  assert.doesNotMatch(text, /fallback holds/);
  assert.equal(lease.now.setpointW, null, "nothing is recommended");
  assert.equal(lease.stopRecommended, false);
  // the same with the lease named, and with 100 % (the top-of-charge caution rides along)
  assert.match(plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 100, targetSocPct: 100, inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 } }).needed.join(" "), /keeps charging past the target/);
  // a path that has a target stop says only that the rate in force is left as it is; nothing in force says only that nothing is to be applied; neither claims a charge goes on
  for (const actuatorProfile of ["TOU_SLOT_EDITOR", "UNCONSTRAINED", "RATE_CONTROLLER_PROPOSED"] as const) {
    const q = plan({ actuatorProfile, elapsedMin: 60, socPct: 85, inForce: { setpointW: 3000, lastChangeAtMin: 0, changesUsed: 0 } });
    assert.equal(q.status, "NO_NEED");
    assert.match(q.needed.join(" "), /the rate in force \(3000 W\) is left as it is/, actuatorProfile);
    assert.doesNotMatch(q.needed.join(" "), /keeps charging|fallback holds/, actuatorProfile);
  }
  const none = plan({ elapsedMin: 60, socPct: 85 });
  assert.equal(none.status, "NO_NEED");
  assert.doesNotMatch(none.needed.join(" "), /keeps charging|fallback holds|rate in force/);
  // 0 W in force means not charging: no lease keeps charging
  assert.doesNotMatch(plan({ elapsedMin: 60, socPct: 85, inForce: { setpointW: 0, lastChangeAtMin: 0, changesUsed: 0 } }).needed.join(" "), /keeps charging/);
  // a rate in force ABOVE a known ceiling is still the STOP (checked before the target): 8000 W against a 6000 W limit
  const stop = plan({ elapsedMin: 60, socPct: 85, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(stop.status, "STOP_RECOMMENDED");
  assert.doesNotMatch(stop.needed.join(" "), /keeps charging past the target/);
});

// ---- round 3 F10: the mutants that survived the behavioural suites (H05 to H32 of the review), each killed by a by-hand assertion of its own --------------------------
test("round 3 F10 H05: the pessimistic world reaches the deadline only when BOTH consistent starts do (a deadline between the two finishes is a miss) (by hand)", () => {
  // the lease at 1900 W, minute 93, reading 90 (1 min old), target 91, deadline 195 (buffer 105): 1.9 x 0.9 = 1.71 kW = 0.082268 points a minute. The start on the plateau
  // (89) reaches the knee in 12.2 minutes, the cliff minute gives 0.0463 points, the tail 0.0102835 points a minute carries the last 0.9537: 198.9. The start past the knee
  // (the knee 90, the fall over) carries its 1 point on that tail: 190.2. The deadline 195 lies between them: the later one decides, so it is NOT reached
  const perMin = (1.9 * 0.9) / 60 / PK;
  const plain = 93 + 1 / perMin + 1 + (1 - (1.125 / 2) * perMin) / (0.125 * perMin);
  const past = 93 + 1 / (0.125 * perMin);
  assert.ok(past < 195 && 195 < plain, "the deadline lies between the two starts: " + past + " < 195 < " + plain);
  const p = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 93, socPct: 90, targetSocPct: 91, bufferMin: 105, inForce: { setpointW: 1900, lastChangeAtMin: -60, changesUsed: 0 } });
  near(band(p).pessimisticHeld.finishMin, plain, 0.05, "the later start");
  assert.equal(band(p).pessimisticHeld.reachedByDeadline, false);
  assert.equal(band(p).pessimistic.reachedByDeadline, false);
  assert.notEqual(p.status, "OK");
  // and with the deadline after both (buffer 90: 210) it is reached
  assert.equal(band(plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 93, socPct: 90, targetSocPct: 91, bufferMin: 90, inForce: { setpointW: 1900, lastChangeAtMin: -60, changesUsed: 0 } })).pessimisticHeld.reachedByDeadline, true);
});

test("round 3 F10 H10, H11: the jump allowance is the resolution, the tolerance and 60 points an hour from the PREVIOUS reading to NOW (by hand)", () => {
  // previous 20 at minute 0, now minute 6 (a reading 1 minute old): 6 minutes = 0.1 hour: 1 + 3 + 60 x 0.1 = 10 points: 30 is plausible, 30.1 is not. Counting the hours only to
  // the reading (5 minutes) would refuse 30 (allowance 9); doubling them (the allowance 16) would accept 30.1
  const at = (socPct: number): GentleNightPlan => plan({ elapsedMin: 6, socPct, socAgeMin: 1, previousSoc: { socPct: 20, elapsedMin: 0 } });
  assert.notEqual(at(30).status, "INPUTS_UNUSABLE");
  assert.equal(at(30).assumptions?.socAtPlanStartPct, 30, "accepted as read");
  assert.deepEqual(at(30.1).codes, ["SOC_IMPLAUSIBLE"]);
  // a longer interval allows more: 30 minutes = 0.5 hour: 1 + 3 + 30 = 34 points
  assert.notEqual(plan({ elapsedMin: 30, socPct: 54, socAgeMin: 1, previousSoc: { socPct: 20, elapsedMin: 0 } }).status, "INPUTS_UNUSABLE");
  assert.deepEqual(plan({ elapsedMin: 30, socPct: 54.1, socAgeMin: 1, previousSoc: { socPct: 20, elapsedMin: 0 } }).codes, ["SOC_IMPLAUSIBLE"]);
});

test("round 3 F10 H21: at exactly minute 0 nothing has charged: a rate in force there is crossed at like a START, so a raise is credited; half a minute later it is held (by hand)", () => {
  // the editor, 2000 W set at minute -200, reading 92 taken at minute 0, target 95: at minute 0 the knee is crossed at the rate in force then, like the START at 3100 W
  // (the same number as the pinned call 30 minutes before the window); a half minute later the optimistic estimate of the reading (92 + 1.0) is past the knee 90 and a
  // rate that has charged is held
  const at = (elapsedMin: number): GentleNightPlan => plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin, socAgeMin: 0, drainBoundW: 0, socPct: 92, targetSocPct: 95, inForce: { setpointW: 2000, lastChangeAtMin: -200, changesUsed: 0 } });
  const zero = at(0);
  assert.equal(zero.now.change, "INCREASE");
  assert.equal(zero.now.setpointW, 3100);
  assert.equal(zero.status, "OK");
  assert.ok(!zero.codes.includes("HELD_PAST_KNEE"));
  const later = at(0.5);
  assert.equal(later.now.change, "KEEP");
  assert.ok(later.codes.includes("HELD_PAST_KNEE"));
});

test("round 3 F10 H26: the efficiency band must be ordered minimum <= expected <= maximum", () => {
  // the defaults are 0.90 <= 0.95 <= 0.97: each order broken on its own is refused, a valid band is not
  for (const params of [{ chargeEffMin: 0.96 }, { chargeEffMax: 0.94 }, { chargeEff: 0.98 }, { chargeEff: 0.89 }, { chargeEffMin: 0.97, chargeEff: 0.95, chargeEffMax: 0.9 }]) {
    assert.deepEqual(plan({ params }).codes, ["PARAMS_INVALID"], JSON.stringify(params));
  }
  assert.equal(plan({ params: { chargeEffMin: 0.92, chargeEff: 0.92, chargeEffMax: 0.92 } }).status, "OK", "equal is allowed");
  assert.equal(plan({ params: { chargeEffMin: 0.8, chargeEff: 0.9, chargeEffMax: 1 } }).status, "OK");
});

test("round 3 F10 H28: the path's setpoint step tightens a coarser parameter step: 150 W becomes the editor's 100 W multiple above it, 200 W, and the minimum follows (by hand)", () => {
  // every path takes 100 W steps; a 150 W step is not a multiple of 100, so it is raised to 200 W (the profile never loosens a parameter): the lowest setpoint is 500 W
  // rounded up to a multiple of 200, 600 W, and a recommendation is a multiple of 200
  const p = plan({ params: { stepW: 150 } });
  assert.equal(p.now.stepW, 200);
  assert.equal(p.now.minW, 600);
  assert.equal((p.now.setpointW as number) % 200, 0);
  assert.equal(p.status, "OK");
  const q = plan({ params: { stepW: 300 } });
  assert.equal(q.now.stepW, 300, "a multiple of 100 stays as given");
  assert.equal((q.now.setpointW as number) % 300, 0);
});

test("round 3 F10 H30: the deadline has not passed AT the deadline minute; it has half a minute later", () => {
  assert.ok(!plan({ elapsedMin: 240, socPct: 70 }).codes.includes("DEADLINE_PASSED_WINDOW_OPEN"));
  assert.ok(plan({ elapsedMin: 240.5, socPct: 70 }).codes.includes("DEADLINE_PASSED_WINDOW_OPEN"));
  assert.ok(!plan({ elapsedMin: 239.5, socPct: 70 }).codes.includes("DEADLINE_PASSED_WINDOW_OPEN"));
});

test("round 3 F10 H31, H32: the knee estimate takes the reading, never the drained SOC, and counts the charge since the reading from the first minute of the window (by hand)", () => {
  // H31: the editor, 2000 W set at minute -200, a reading of 88.6 taken at minute -10 (15 minutes old at minute 5), 3000 W of drain bound. Nothing charged before the window:
  // 10 idle minutes = 0.5 kWh = 1.728 points of drain, so the plan starts from 86.87; but the OPTIMISTIC estimate of the reading takes no drain (the bound is pessimistic): 88.6
  // + 1.0 + the charge since the reading (5 minutes at 2000 W x 1.1 = 0.634 points) = 90.23, past the knee: the rate in force is HELD. From the drained SOC it would be 88.51 and the
  // raise would be credited
  const h31 = plan({ actuatorProfile: "TOU_SLOT_EDITOR", elapsedMin: 5, socAgeMin: 15, socPct: 88.6, targetSocPct: 95, drainBoundW: 3000, inForce: { setpointW: 2000, lastChangeAtMin: -200, changesUsed: 0 } });
  near(h31.assumptions?.socAtPlanStartPct, 88.6 - (3 * 10) / 60 / OPT, 0.006, "the plan starts from the drained SOC");
  near(h31.assumptions?.kneeEstimatePct, 88.6 + 1.0 + (5 * 2000 * 1.1) / 60000 / OPT, 0.006, "the knee estimate does not");
  assert.equal(h31.now.change, "KEEP");
  assert.ok(h31.codes.includes("HELD_PAST_KNEE"));
  // H32: minute 1, a reading 1 minute old (taken at minute 0), 3000 W in force since before the window, 88.85: the charge since the reading is 1 minute at 3000 W x 1.1 = 0.190
  // points, so 88.85 + 1.0 + 0.190 = 90.04: held. Skipping the first minute of the window (elapsed > 1) would leave 89.85 and credit a raise
  const h32 = plan({ actuatorProfile: "UNCONSTRAINED", elapsedMin: 1, socAgeMin: 1, socPct: 88.85, targetSocPct: 95, inForce: { setpointW: 3000, lastChangeAtMin: -60, changesUsed: 0 } });
  near(h32.assumptions?.chargeSinceReadingPct, (1 * 3000 * 1.1) / 60000 / OPT, 0.006, "one minute of charge");
  assert.equal(h32.now.change, "KEEP");
  assert.ok(h32.codes.includes("HELD_PAST_KNEE"));
  // a hair lower (88.8: 89.99) the knee is surely ahead and the raise is credited
  assert.equal(plan({ actuatorProfile: "UNCONSTRAINED", elapsedMin: 1, socAgeMin: 1, socPct: 88.8, targetSocPct: 95, inForce: { setpointW: 3000, lastChangeAtMin: -60, changesUsed: 0 } }).now.change, "INCREASE");
});

test("round 3 F10 H08, H16, H17, H25: the knees of the expected and optimistic worlds stay below 100, the buffer that fits stops at 120, the expected finish is from now, a stale demand is not used by the STOP check (by hand)", () => {
  // H08: the expected knee is the pessimistic one plus 5 and the optimistic plus 10, at most 99.5 (a world with a knee at 100 would never fall)
  const k = plan().assumptions as Record<string, number>;
  assert.deepEqual([k.kneePessimisticPct, k.kneeExpectedPct, k.kneeOptimisticPct], [90, 95, 99.5]);
  const k97 = plan({ params: { kneeSocPct: 97 } }).assumptions as Record<string, number>;
  assert.deepEqual([k97.kneeExpectedPct, k97.kneeOptimisticPct], [99.5, 99.5]);
  const k996 = plan({ params: { kneeSocPct: 99.6 } }).assumptions as Record<string, number>;
  assert.deepEqual([k996.kneeExpectedPct, k996.kneeOptimisticPct], [99.6, 99.6], "a pessimistic knee at or above 99.5 is not raised");
  // H16: 3 points x 0.346412 kWh at the minimum 0.45 kW = 138.6 minutes, 161.4 before the window end (300): the largest buffer is 120, not the 160 that fits
  const roomy = plan({ targetSocPct: 22, socPct: 20 });
  assert.equal(roomy.now.setpointW, 500);
  assert.equal(roomy.bufferThatWouldFitMin, 120);
  // H17: before the window the expected finish is counted from NOW: 90 minutes more than from the window start
  const early = plan({ elapsedMin: -90, preWindowDrainW: 0 });
  const fin = early.expectedFinish as NonNullable<typeof early.expectedFinish>;
  near(fin.inMin, fin.atMin + 90, 0.11, "the expected finish from now");
  // H25: a known grid limit with a STALE demand is DEMAND_UNKNOWN: the STOP check then compares with the limit alone (8000 x 0.85 / 1.1 = 6181, floored 6100 W), not with a
  // headroom taken from the stale demand (3400 W): 5200 W in force is below 6100 W, so no STOP
  const stale = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 40, household: { gridImportLimitW: 8000, demandPeakW: 3000, demandAgeMin: 20 }, inForce: { setpointW: 5200, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(stale.status, "INPUTS_UNUSABLE");
  assert.deepEqual(stale.codes, ["DEMAND_UNKNOWN"]);
  assert.equal(stale.stopRecommended, false);
  // the same demand, fresh, is the headroom (8000 - 3000 x 1.2) x 0.85 / 1.1 = 3400 W: 5200 W is above it, a STOP
  const fresh = plan({ actuatorProfile: "FREE_POWER_LEASE", elapsedMin: 60, socPct: 40, household: { gridImportLimitW: 8000, demandPeakW: 3000, demandAgeMin: 15 }, inForce: { setpointW: 5200, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(fresh.status, "STOP_RECOMMENDED");
  assert.equal(fresh.now.ceilingW, 3400);
});

test("round 3 F10 H18, H19: a re-plan reads the world's DISPLAYED reading and keeps the reading uncertainty: a world whose own reading puts the knee within reach holds its rate (by hand)", () => {
  // UNCONSTRAINED, minute 100, reading 85.3 (1 minute old), 3000 W set at minute 95 (the dwell of 30 minutes holds it), target 95. The first re-plan is 30 minutes on (tick 130).
  // EXPECTED world: 0.95 x 3 kW / 60 / 0.317 = 0.14984 points a minute: 89.795 at the tick, +1.0 of uncertainty = 90.795 >= 90: the knee may be passed, HOLD (no later point).
  //   Without the uncertainty (89.795 < 90) it would plan a raise at 130 (H19).
  // PESSIMISTIC world: starts at 84.3 (reading - 1.0), 0.12991 points a minute: 88.197 at the tick, DISPLAYED 89.197, +1.0 = 90.197 >= 90: HOLD, so it is the held world. Read at its
  //   true position (88.197 + 1.0 < 90) it would raise (H18)
  const p = plan({ actuatorProfile: "UNCONSTRAINED", elapsedMin: 100, socPct: 85.3, targetSocPct: 95, inForce: { setpointW: 3000, lastChangeAtMin: 95, changesUsed: 0 } });
  assert.equal(p.now.change, "KEEP");
  assert.ok(p.codes.includes("HELD_DWELL"));
  assert.equal(p.trajectory.length, 1, JSON.stringify(p.trajectory));
  assert.deepEqual(band(p).pessimistic, band(p).pessimisticHeld, "the pessimistic policy world never changes the rate");
  // the tick sits 30 minutes on: the arithmetic of the comments
  const exp = 85.3 + 30 * ((3 * 0.95) / 60 / 0.317);
  const pess = 85.3 - 1.0 + 30 * ((3 * 0.9) / 60 / PK);
  assert.ok(exp < 90 && exp + 1.0 >= 90, "expected world reads " + exp);
  assert.ok(pess + 1.0 < 90 && pess + 2.0 >= 90, "pessimistic world is at " + pess);
});
