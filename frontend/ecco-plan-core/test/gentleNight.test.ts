// Gentle night planner (src/gentleNight.ts), unit and property tests. READ ONLY: these drive a pure function. Seeded, so a failure reproduces.
// Independence note: the numbers marked "by hand" are worked out here from the stated model, not copied from the code; the closed-loop file checks the
// planner against a separately written truth battery (test/support/gentleNightTruth.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { planGentleNight, windowFromSlotTable, windowTouchesClockChange, NIGHT_CODES, DEFAULT_NIGHT_PARAMS } from "../src/gentleNight.ts";
import type { GentleNightInput, GentleNightPlan } from "../src/gentleNight.ts";
import * as NIGHT_MODULE from "../src/gentleNight.ts";
import { maxChargePowerCeiling } from "../src/gentleController.ts";
import { exampleBaseline, rng, slot } from "./fixtures.ts";

const ORD = { changeAtMin: 0, deltaMin: 0 } as const;
const base: GentleNightInput = {
  targetSocPct: 80, chargeWindow: { startMin: 30, endMin: 330 }, clockDay: ORD, elapsedMin: 0, socPct: 20, socAgeMin: 1, capacityKwh: 31.7, ceilings: [maxChargePowerCeiling(8000, 8000)],
};
const plan = (over: Partial<GentleNightInput> = {}): GentleNightPlan => planGentleNight({ ...base, ...over });

test("by hand: a plateau-only target needs exactly the rate the arithmetic gives (pessimistic start 19, capacity 31.7 x 1.06 / 0.97, efficiency 0.90, 4 h)", () => {
  // 60 % target: (60 - 19) points x (31.7 x 1.06 / 0.97 / 100 = 0.34641 kWh per point) = 14.203 kWh; at 0.9 x S for 4 h: S >= 3945 W, so 4000 W.
  const p = plan({ targetSocPct: 60 });
  assert.equal(p.status, "OK");
  assert.equal(p.now.setpointW, 4000);
  assert.equal(p.now.neededW, 4000);
  assert.equal(p.deadlineMin, 240);
  assert.equal(p.windowRealMin, 300);
  // one step lower misses on a path that cannot change (3900 W gives 14.04 kWh in 4 h, 0.16 kWh short)
  const low = plan({ targetSocPct: 60, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 } });
  const lowFinish = (low.band as NonNullable<typeof low.band>).pessimistic.finishMin as number;
  assert.ok(lowFinish > 240 && lowFinish < 300, "pessimistic finish " + lowFinish);
  assert.equal(low.status, "TARGET_AT_RISK");
  assert.equal(plan({ targetSocPct: 60, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: 4000, lastChangeAtMin: 0, changesUsed: 0 } }).status, "OK");
  // on a path that can change, the same low rate is raised at the first re-plan after the dwell; no path makes that raise by itself, so the status is
  // judged with the rate in force held: TARGET_AT_RISK (stricter than the earlier OK, which is kept as a killed mutant), and it says it relies on the raise
  const adapt = plan({ targetSocPct: 60, actuatorProfile: "UNCONSTRAINED", inForce: { setpointW: 3900, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(adapt.status, "TARGET_AT_RISK");
  assert.ok(adapt.codes.includes("RELIES_ON_LATER_CHANGE"));
  assert.equal(adapt.now.change, "KEEP");
  assert.equal(adapt.band?.pessimistic.reachedByDeadline, true, "the planned raise would make it");
  assert.equal(adapt.band?.pessimisticHeld.reachedByDeadline, false, "the rate in force alone does not");
});

test("by hand: the finish time of the pessimistic world above the knee (8000 W held, reading 85, target 93): plateau, a one minute fall, then the tail", () => {
  // start 84; plateau 84 -> 90 = 6 points x 0.34641 = 2.0785 kWh at 7.2 kW = 17.3 min; the fall minute delivers (7.2 + 0.9) / 2 / 60 = 0.0675 kWh = 0.195 points;
  // the rest 2.805 points x 0.34641 = 0.9717 kWh at the tail 0.125 x 8000 x 0.9 = 0.9 kW = 64.7 min: about 83.0 min in all.
  const p = plan({ targetSocPct: 93, socPct: 85, inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } });
  const fin = (p.band as NonNullable<typeof p.band>).pessimistic.finishMin as number;
  assert.ok(Math.abs(fin - 83.0) < 0.4, "pessimistic finish " + fin);
});

test("statuses: OK, TARGET_AT_RISK (inside the buffer), UNREACHABLE, NO_NEED, each with the highest safe rate when it cannot be met and the target never lowered", () => {
  assert.equal(plan().status, "OK");
  const risk = plan({ targetSocPct: 95, socPct: 40 });
  assert.equal(risk.status, "TARGET_AT_RISK");
  assert.equal(risk.now.setpointW, 8000, "the highest safe rate");
  assert.equal(risk.targetSocPct, 95);
  assert.ok(risk.codes.includes("RATE_AT_CEILING") && risk.codes.includes("PESSIMISTIC_MISSES_DEADLINE") && risk.codes.includes("TARGET_ABOVE_KNEE"));
  assert.ok(typeof risk.bufferThatWouldFitMin === "number" && risk.bufferThatWouldFitMin % 5 === 0 && risk.bufferThatWouldFitMin < 60);
  const none = plan({ targetSocPct: 100, socPct: 10, bufferMin: 120, ceilings: [maxChargePowerCeiling(8000, 3000)] });
  assert.equal(none.status, "UNREACHABLE");
  assert.equal(none.now.setpointW, 3000);
  assert.equal(none.targetSocPct, 100);
  assert.equal(none.bufferThatWouldFitMin, null);
  const done = plan({ socPct: 80 });
  assert.equal(done.status, "NO_NEED");
  assert.equal(done.now.setpointW, null);
  assert.deepEqual(done.codes, ["AT_TARGET"]);
  assert.ok(plan({ socPct: 100, targetSocPct: 100 }).codes.includes("TOP_OF_CHARGE_TAIL"));
});

test("the band is ordered (pessimistic is never earlier than expected, expected never earlier than optimistic) and the SOC at the deadline likewise", () => {
  const r = rng(11);
  for (let i = 0; i < 300; i++) {
    const p = plan({ socPct: 5 + Math.floor(r() * 70), targetSocPct: 60 + Math.floor(r() * 41), bufferMin: 5 * Math.floor(r() * 25), elapsedMin: Math.floor(r() * 150), capacityKwh: 15 + r() * 30 });
    if (p.band === null) continue;
    const f = (w: { finishMin: number | null }): number => (w.finishMin === null ? Infinity : w.finishMin);
    assert.ok(f(p.band.pessimistic) >= f(p.band.expected) - 1e-9 && f(p.band.expected) >= f(p.band.optimistic) - 1e-9, JSON.stringify(p.band));
    assert.ok(p.band.pessimistic.socAtDeadlinePct <= p.band.expected.socAtDeadlinePct + 1e-9 && p.band.expected.socAtDeadlinePct <= p.band.optimistic.socAtDeadlinePct + 1e-9);
    assert.ok(p.band.pessimistic.socAtDeadlinePct <= 100 && p.band.optimistic.socAtDeadlinePct <= 100);
  }
});

test("the deadline: the window end minus the buffer (default 60, 0 to 120 in steps of 5) from the slot-table times; anything else is refused", () => {
  assert.equal(plan().deadlineMin, 240);
  assert.equal(plan({ bufferMin: 0 }).deadlineMin, 300);
  assert.equal(plan({ bufferMin: 120 }).deadlineMin, 180);
  assert.equal(plan({ bufferMin: 35 }).deadlineMin, 265);
  for (const bad of [7, -5, 125, NaN, 61, 0.5, "60" as unknown as number, null as unknown as number]) {
    const p = plan({ bufferMin: bad });
    assert.equal(p.status, "INPUTS_UNUSABLE", String(bad));
    assert.deepEqual(p.codes, ["BUFFER_INVALID"]);
  }
  // a window across midnight: 22:00 to 04:00 is 6 h
  const wrap = plan({ chargeWindow: { startMin: 22 * 60, endMin: 4 * 60 } });
  assert.equal(wrap.windowRealMin, 360);
  assert.equal(wrap.deadlineMin, 300);
  assert.equal(plan({ chargeWindow: { startMin: 600, endMin: 600 } }).codes[0], "WINDOW_INVALID");
  assert.equal(plan({ chargeWindow: { startMin: 600.5, endMin: 700 } }).codes[0], "WINDOW_INVALID");
  assert.equal(plan({ chargeWindow: { startMin: 600, endMin: 1440 } }).codes[0], "WINDOW_INVALID");
  assert.equal(plan({ chargeWindow: null as unknown as { startMin: number; endMin: number } }).codes[0], "WINDOW_INVALID");
  for (const t of [9, 5, 100.5, 101, NaN, null, undefined, "80"]) assert.deepEqual(plan({ targetSocPct: t as unknown as number }).codes, ["TARGET_INVALID"], String(t));
  assert.equal(plan({ targetSocPct: 10 }).status, "NO_NEED", "10 is a valid target (already reached)");
});

test("clock-change nights: a skipped or repeated local hour inside (or touching) the window is refused; a window clear of it is planned", () => {
  const spring = { changeAtMin: 120, deltaMin: 60 } as const; // 02:00 -> 03:00
  const autumn = { changeAtMin: 180, deltaMin: -60 } as const; // 03:00 -> 02:00 (02:00 to 03:00 repeats)
  for (const day of [spring, autumn]) {
    for (const w of [{ startMin: 30, endMin: 330 }, { startMin: 22 * 60, endMin: 4 * 60 }, { startMin: 150, endMin: 160 }, { startMin: 23 * 60, endMin: 2 * 60 + 30 }]) {
      const p = plan({ chargeWindow: w, clockDay: day });
      assert.equal(p.status, "CLOCK_CHANGE_NIGHT_REFUSED", JSON.stringify([day, w]));
      assert.deepEqual(p.codes, ["CLOCK_CHANGE_NIGHT"]);
      assert.equal(p.now.setpointW, null);
    }
    for (const w of [{ startMin: 10 * 60, endMin: 15 * 60 }, { startMin: 5 * 60 + 30, endMin: 9 * 60 }, { startMin: 18 * 60, endMin: 21 * 60 }, { startMin: 4 * 60 + 30, endMin: 7 * 60 }]) {
      assert.notEqual(plan({ chargeWindow: w, clockDay: day }).status, "CLOCK_CHANGE_NIGHT_REFUSED", JSON.stringify([day, w]));
    }
  }
  assert.equal(windowTouchesClockChange(30, 330, ORD), false);
  assert.equal(windowTouchesClockChange(30, 330, spring), true);
  // after the change the real length is known again: a spring window that opens after 03:00 is planned, the autumn repeated hour reaches to 04:00 (edge included)
  assert.equal(windowTouchesClockChange(3 * 60 + 30, 6 * 60, spring), false);
  assert.equal(windowTouchesClockChange(3 * 60 + 30, 6 * 60, autumn), true);
  assert.equal(windowTouchesClockChange(4 * 60, 6 * 60, autumn), true);
  assert.equal(windowTouchesClockChange(4 * 60 + 5, 6 * 60, autumn), false);
  assert.equal(plan({ clockDay: { changeAtMin: 120, deltaMin: 30 } as unknown as typeof spring }).codes[0], "CLOCK_DAY_INVALID");
  // the refusal comes before any data check: stale data on a clock-change night is still a refusal, not an input problem
  assert.equal(plan({ clockDay: spring, socAgeMin: 99 }).status, "CLOCK_CHANGE_NIGHT_REFUSED");
});

test("the window comes from the slot table: the one run of Grid slots, its start and the start of the slot after it; ambiguous tables give nothing", () => {
  const w = windowFromSlotTable(exampleBaseline());
  assert.deepEqual(w, { startMin: 23 * 60 + 30, endMin: 5 * 60, powerW: 5000, targetSoc: 90 });
  const two = [slot(60, 5000, 90, "Grid"), slot(120, 5000, 15, "None"), slot(180, 5000, 90, "Grid"), slot(240, 5000, 15, "None")];
  assert.equal(windowFromSlotTable(two), null, "two separate runs are ambiguous");
  const merged = [slot(60, 5000, 90, "Grid"), slot(120, 5000, 90, "Grid"), slot(180, 5000, 15, "None"), slot(900, 5000, 15, "None")];
  assert.deepEqual(windowFromSlotTable(merged), { startMin: 60, endMin: 180, powerW: 5000, targetSoc: 90 });
  const differ = [slot(60, 5000, 90, "Grid"), slot(120, 6000, 90, "Grid"), slot(180, 5000, 15, "None"), slot(900, 5000, 15, "None")];
  assert.equal(windowFromSlotTable(differ), null, "slots of one run that disagree are ambiguous");
  assert.equal(windowFromSlotTable([slot(0, 5000, 15, "None"), slot(600, 5000, 15, "None")]), null);
  assert.equal(windowFromSlotTable([slot(0, 5000, 15, "Grid"), slot(600, 5000, 15, "Grid")]), null);
  assert.equal(windowFromSlotTable([]), null);
  const win = windowFromSlotTable(exampleBaseline()) as NonNullable<typeof w>;
  assert.equal(plan({ chargeWindow: { startMin: win.startMin, endMin: win.endMin } }).windowRealMin, 330);
});

test("unusable inputs: unknown, stale or implausible data is never guessed and never charged on", () => {
  const cases: Array<[string, Partial<GentleNightInput>, string]> = [
    ["no SOC", { socPct: null }, "NO_SOC"],
    ["a SOC that is not a number", { socPct: NaN }, "NO_SOC"],
    ["stale SOC", { socAgeMin: 16 }, "STALE_SOC"],
    ["SOC age unknown", { socAgeMin: null }, "STALE_SOC"],
    ["negative age", { socAgeMin: -1 }, "STALE_SOC"],
    ["SOC above 100", { socPct: 101 }, "SOC_IMPLAUSIBLE"],
    ["SOC below 0", { socPct: -1 }, "SOC_IMPLAUSIBLE"],
    ["a reading that fell 10 points", { socPct: 20, previousSoc: { socPct: 30, elapsedMin: -10 } }, "SOC_IMPLAUSIBLE"],
    ["a reading that jumped 20 points in 6 minutes", { socPct: 40, elapsedMin: 6, previousSoc: { socPct: 20, elapsedMin: 0 } }, "SOC_IMPLAUSIBLE"],
    ["a previous reading from the future", { previousSoc: { socPct: 20, elapsedMin: 5 } }, "SOC_IMPLAUSIBLE"],
    ["no capacity", { capacityKwh: null }, "CAPACITY_UNUSABLE"],
    ["zero capacity", { capacityKwh: 0 }, "CAPACITY_UNUSABLE"],
    ["negative capacity", { capacityKwh: -3 }, "CAPACITY_UNUSABLE"],
    ["no ceilings at all", { ceilings: [] }, "NO_SAFE_CEILING"],
    ["an unknown ceiling", { ceilings: [{ name: "owner", watts: null }] }, "NO_SAFE_CEILING"],
    ["a stale only ceiling", { ceilings: [{ name: "owner", watts: 8000, ageMin: 90 }] }, "NO_SAFE_CEILING"],
    ["a ceiling below the minimum", { ceilings: [maxChargePowerCeiling(8000, 300)] }, "CEILING_BELOW_MIN"],
    ["the window over", { elapsedMin: 300 }, "WINDOW_OVER"],
    ["an elapsed time that is not a number", { elapsedMin: NaN }, "ELAPSED_INVALID"],
    ["an actuator profile that does not exist", { actuatorProfile: "MAGIC" as unknown as "UNCONSTRAINED" }, "PROFILE_INVALID"],
    ["an in-force record that is garbage", { inForce: { setpointW: "x" as unknown as number, lastChangeAtMin: null, changesUsed: 0 } }, "INPUT_INVALID"],
    ["a parameter out of bounds", { params: { setpointOvershoot: 2 } }, "PARAMS_INVALID"],
    ["a parameter that is not a number", { params: { kneeSocPct: "90" as unknown as number } }, "PARAMS_INVALID"],
    ["tail fractions out of order", { params: { tailFraction: 0.5 } }, "PARAMS_INVALID"],
  ];
  for (const [name, over, code] of cases) {
    const p = plan(over);
    assert.equal(p.status, "INPUTS_UNUSABLE", name);
    assert.ok(p.codes.includes(code as never), name + ": " + p.codes.join(","));
    assert.equal(p.now.setpointW, null, name);
    assert.equal(p.trajectory.length, 0);
    assert.equal(p.band, null);
    assert.equal(p.actuationSupported, false);
  }
  assert.equal(planGentleNight(null as unknown as GentleNightInput).codes[0], "INPUT_INVALID");
  // the age limit is inclusive; with nothing in force the battery supplied the house for those 15 minutes, so a drain bound is needed (confirmation
  // review MAJOR 3): without one the plan is refused, never guessed; with 0 W given explicitly the SOC is the reading
  assert.equal(plan({ socAgeMin: 15, drainBoundW: 0 }).status, "OK", "the age limit is inclusive");
  assert.deepEqual(plan({ socAgeMin: 15 }).codes, ["DRAIN_UNKNOWN_AGED_READING"]);
  assert.equal(plan({ elapsedMin: -721 }).codes[0], "ELAPSED_INVALID");
});

test("household: an unknown grid limit applies no cap and says so; a known one needs a fresh demand (never guessed) and caps the rate", () => {
  const free = plan();
  assert.ok(free.codes.includes("GRID_LIMIT_UNKNOWN_NO_CAP"));
  assert.ok(free.needed.some((x) => /grid import limit is unknown/.test(x)));
  assert.equal(free.now.ceilingW, 8000);
  assert.equal(plan({ household: { gridImportLimitW: 8000 } }).codes[0], "DEMAND_UNKNOWN");
  assert.equal(plan({ household: { gridImportLimitW: 8000, demandPeakW: null, demandAgeMin: 1 } }).codes[0], "DEMAND_UNKNOWN");
  assert.equal(plan({ household: { gridImportLimitW: 8000, demandPeakW: 1000, demandAgeMin: null } }).codes[0], "DEMAND_UNKNOWN");
  assert.equal(plan({ household: { gridImportLimitW: 8000, demandPeakW: 1000, demandAgeMin: 16 } }).codes[0], "DEMAND_UNKNOWN");
  assert.equal(plan({ household: { gridImportLimitW: 8000, gridImportLimitAgeMin: 61, demandPeakW: 1000, demandAgeMin: 1 } }).codes[0], "GRID_LIMIT_STALE");
  // by hand: (8000 - 2000 x 1.2) x 0.85 / 1.1 = 4327 W, floored to 4300 W
  const cap = plan({ household: { gridImportLimitW: 8000, demandPeakW: 2000, demandAgeMin: 1, gridImportLimitAgeMin: 5 }, targetSocPct: 60 });
  assert.equal(cap.now.ceilingW, 4300);
  assert.equal(cap.now.ceilingName, "grid_headroom");
  assert.ok(!cap.codes.includes("GRID_LIMIT_UNKNOWN_NO_CAP"));
  assert.equal(cap.now.setpointW, 4300 >= 4000 ? 4000 : cap.now.setpointW);
  assert.equal(plan({ household: { gridImportLimitW: 3000, demandPeakW: 2500, demandAgeMin: 1 } }).codes[0], "HEADROOM_BELOW_MIN");
});

test("the ceiling is the smaller of the firmware bound (8000) and the owner limit; a loose helper default never raises it; a battery-side limit takes the overshoot", () => {
  assert.equal(plan({ ceilings: [maxChargePowerCeiling(8000, 5000)] }).now.ceilingW, 5000);
  assert.equal(plan({ ceilings: [maxChargePowerCeiling(8000, 65500)] }).now.ceilingW, 8000);
  assert.equal(plan({ ceilings: [maxChargePowerCeiling(8000, 5050)] }).now.ceilingW, 5000, "floored to a step");
  assert.equal(plan({ ceilings: [maxChargePowerCeiling(8000, 8000), { name: "battery", watts: 7700, basis: "BATTERY_DC" }] }).now.ceilingW, 7000, "7700 / 1.1");
  assert.equal(plan({ ceilings: [maxChargePowerCeiling(8000, 8000), { name: "stale", watts: 3000, ageMin: 500 }] }).now.ceilingW, 3000, "a stale lower value still caps");
  assert.ok(plan({ ceilings: [{ name: "owner", watts: 8000 }] }).codes.includes("CEILING_AGE_UNKNOWN"));
  assert.ok(!plan({ ceilings: [maxChargePowerCeiling(8000, 8000, 3)] }).codes.includes("CEILING_AGE_UNKNOWN"));
  assert.equal(plan({ ceilings: [maxChargePowerCeiling(8000, 8000)], params: { hardMaxW: 6000 } }).now.ceilingW, 6000);
});

test("the learned capacity counts only when it is the larger (more energy needed), and never lowers the rate", () => {
  const a = plan({ targetSocPct: 70 }).now.setpointW as number;
  assert.ok((plan({ targetSocPct: 70, learnedCapacityKwh: 36 }).now.setpointW as number) > a);
  assert.equal(plan({ targetSocPct: 70, learnedCapacityKwh: 20 }).now.setpointW, a);
  assert.equal(plan({ targetSocPct: 70, learnedCapacityKwh: null }).now.setpointW, a);
});

test("before the window opens: the plan starts at the window start from the SOC less the given drain bound, and says so; with no drain bound nothing is recommended", () => {
  // with a drain bound of 0 W given explicitly the SOC is unchanged until the window opens (the earlier default, now only by explicit assumption)
  const early = plan({ elapsedMin: -90, preWindowDrainW: 0 });
  assert.ok(early.codes.includes("BEFORE_WINDOW"));
  assert.equal(early.trajectory[0]?.atMin, 0);
  assert.equal(early.trajectory[0]?.inMin, 90);
  assert.equal(early.now.setpointW, plan().now.setpointW, "the same rate as at the window start");
  assert.equal(early.deadlineInMin, 330);
  // no drain bound: the evening load drains the battery before the window, so the SOC at the window start is not known: refused, never OK
  const blind = plan({ elapsedMin: -90 });
  assert.equal(blind.status, "INPUTS_UNUSABLE");
  assert.deepEqual(blind.codes, ["PRE_WINDOW_DRAIN_UNKNOWN"]);
  assert.equal(blind.now.setpointW, null);
  for (const bad of [null, NaN, -1, 30001, "600" as unknown as number]) assert.deepEqual(plan({ elapsedMin: -90, preWindowDrainW: bad }).codes, ["PRE_WINDOW_DRAIN_UNKNOWN"], String(bad));
});

test("after the deadline with the window still open: best effort, never OK, never a decrease", () => {
  const late = plan({ elapsedMin: 250, socPct: 70, inForce: { setpointW: 6000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.ok(late.codes.includes("DEADLINE_PASSED_WINDOW_OPEN"));
  assert.ok(late.status === "TARGET_AT_RISK" || late.status === "UNREACHABLE");
  assert.notEqual(late.now.change, "DECREASE");
});

test("the actuator profiles: FREE_POWER_LEASE is one flat rate; TOU_SLOT_EDITOR has at most one conditional change; the rate controller adapts, honestly stated", () => {
  const night = { socPct: 20, targetSocPct: 80 };
  const free = plan({ ...night, actuatorProfile: "FREE_POWER_LEASE" });
  assert.equal(free.trajectory.length, 1);
  assert.equal(free.profile?.adaptive, false);
  assert.match(free.profile?.adaptiveNote ?? "", /fixed at the START/);
  const tou = plan({ ...night, actuatorProfile: "TOU_SLOT_EDITOR" });
  assert.ok(tou.trajectory.length <= 2);
  assert.equal(tou.profile?.adaptive, false);
  assert.equal(tou.profile?.ownerConfirmationPerChange, true);
  assert.match(tou.needed.join(" "), /typed phrase/);
  for (const p of tou.trajectory.slice(1)) assert.equal(p.conditional, true);
  const rc = plan({ ...night, actuatorProfile: "RATE_CONTROLLER_PROPOSED" });
  assert.ok(rc.trajectory.length > 2, "the expected world is ahead of the pessimistic one, so the policy plans decreases");
  assert.ok(rc.trajectory.length - 1 <= 6);
  assert.equal(rc.profile?.adaptive, true);
  assert.match(rc.profile?.adaptiveNote ?? "", /does not exist/);
  assert.equal(rc.profile?.existsToday, false);
  assert.match(rc.needed.join(" "), /does not exist/);
  for (let i = 1; i < rc.trajectory.length; i++) {
    const a = rc.trajectory[i - 1];
    const b = rc.trajectory[i];
    assert.ok(a !== undefined && b !== undefined && b.atMin - a.atMin >= 30 - 1e-9, "30 minutes dwell between planned changes");
    assert.equal(b.conditional, true);
    assert.ok(b.setpointW >= 500 && b.setpointW % 100 === 0 && b.setpointW <= 8000);
  }
  assert.equal(rc.trajectory[0]?.conditional, false);
  // the start rate is the same on every path (the pessimistic need), the paths only differ in what may change later
  assert.equal(free.now.setpointW, rc.now.setpointW);
  assert.equal(free.now.setpointW, tou.now.setpointW);
});

test("in force: dwell, budget, a held rate after the knee, a forced decrease below the ceiling, hysteresis and slack", () => {
  // the generic model is named explicitly (the default is now the most restrictive existing path); the calls that name another path keep it
  const plan = (over: Partial<GentleNightInput> = {}): GentleNightPlan => planGentleNight({ ...base, actuatorProfile: "UNCONSTRAINED", ...over });
  const N = plan({ elapsedMin: 100, socPct: 40 }).now.setpointW as number; // the rate needed now with nothing in force
  const low = 2000;
  assert.ok(low < N);
  // an infeasible rate in force: raised after the dwell, held inside it
  const held = plan({ elapsedMin: 100, socPct: 40, inForce: { setpointW: low, lastChangeAtMin: 80, changesUsed: 0 } });
  assert.equal(held.now.change, "KEEP");
  assert.ok(held.codes.includes("HELD_DWELL"));
  assert.equal(held.now.setpointW, low);
  assert.equal(held.now.neededW, N, "what is needed is still said");
  const raised = plan({ elapsedMin: 100, socPct: 40, inForce: { setpointW: low, lastChangeAtMin: 60, changesUsed: 0 } });
  assert.equal(raised.now.change, "INCREASE");
  assert.equal(raised.now.setpointW, N);
  assert.ok(raised.codes.includes("INCREASE_NEEDED"));
  // the budget
  const spent = plan({ elapsedMin: 100, socPct: 40, inForce: { setpointW: low, lastChangeAtMin: 0, changesUsed: 6 } });
  assert.equal(spent.now.change, "KEEP");
  assert.ok(spent.codes.includes("HELD_BUDGET"));
  const touSpent = plan({ elapsedMin: 100, socPct: 40, actuatorProfile: "TOU_SLOT_EDITOR", inForce: { setpointW: low, lastChangeAtMin: 0, changesUsed: 1 } });
  assert.ok(touSpent.codes.includes("HELD_BUDGET"));
  const touDwell = plan({ elapsedMin: 100, socPct: 40, actuatorProfile: "TOU_SLOT_EDITOR", inForce: { setpointW: low, lastChangeAtMin: 50, changesUsed: 0 } });
  assert.ok(touDwell.codes.includes("HELD_DWELL"), "the editor's dwell is 60 minutes, not 30");
  const fixed = plan({ elapsedMin: 100, socPct: 40, actuatorProfile: "FREE_POWER_LEASE", inForce: { setpointW: low, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.ok(fixed.codes.includes("HELD_PATH_FIXED"));
  assert.equal(fixed.now.setpointW, low);
  assert.equal(fixed.status === "OK", false, "a rate that cannot be changed and is too low is not called OK");
  // past the knee the rate is held
  const knee = plan({ elapsedMin: 100, socPct: 93, targetSocPct: 95, inForce: { setpointW: 5200, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(knee.now.change, "KEEP");
  assert.equal(knee.now.setpointW, 5200);
  assert.ok(knee.codes.includes("HELD_PAST_KNEE"));
  // forced below the ceiling whatever the dwell and the budget say
  const forced = plan({ elapsedMin: 100, socPct: 40, ceilings: [maxChargePowerCeiling(8000, 6000)], inForce: { setpointW: 8000, lastChangeAtMin: 99, changesUsed: 6 } });
  assert.equal(forced.now.setpointW, 6000);
  assert.equal(forced.now.change, "DECREASE");
  assert.ok(forced.codes.includes("FORCED_BELOW_CEILING"));
  // hysteresis: a rate only slightly above the need stays; one far above comes down to a rate that keeps the slack
  const N2 = plan({ elapsedMin: 100, socPct: 60 }).now.setpointW as number;
  const near = plan({ elapsedMin: 100, socPct: 60, inForce: { setpointW: N2 + 300, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(near.now.change, "KEEP");
  assert.equal(near.now.setpointW, N2 + 300);
  const far = plan({ elapsedMin: 100, socPct: 60, inForce: { setpointW: N2 + 3000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.equal(far.now.change, "DECREASE");
  assert.ok(far.codes.includes("DECREASE_SAVES"));
  assert.ok((far.now.setpointW as number) >= N2 && (far.now.setpointW as number) <= N2 + 2500);
  assert.ok((far.marginMin as number) >= 15 - 0.11, "the decrease keeps 15 minutes of slack to the deadline: " + far.marginMin);
  // a decrease is never recommended when the target is at risk
  const risk = plan({ targetSocPct: 95, socPct: 40, elapsedMin: 100, inForce: { setpointW: 8000, lastChangeAtMin: 0, changesUsed: 0 } });
  assert.ok(risk.status === "TARGET_AT_RISK" || risk.status === "UNREACHABLE");
  assert.notEqual(risk.now.change, "DECREASE");
});

test("outputs are well formed: steps of 100 W, never below 500 W, never above the ceiling, codes from the closed list, the expected finish as a wall-clock time", () => {
  const r = rng(2024);
  let seen = 0;
  for (let i = 0; i < 400; i++) {
    const limit = [8000, 6000, 3000][Math.floor(r() * 3)] as number;
    const p = plan({
      socPct: Math.floor(r() * 100), targetSocPct: 10 + Math.floor(r() * 91), bufferMin: 5 * Math.floor(r() * 25), elapsedMin: Math.floor(r() * 320) - 20, capacityKwh: 8 + r() * 40,
      ceilings: [maxChargePowerCeiling(8000, limit)], actuatorProfile: (["UNCONSTRAINED", "FREE_POWER_LEASE", "TOU_SLOT_EDITOR", "RATE_CONTROLLER_PROPOSED"] as const)[Math.floor(r() * 4)] as "UNCONSTRAINED",
    });
    for (const c of p.codes) assert.ok((NIGHT_CODES as readonly string[]).includes(c), c);
    assert.equal(p.reasons.length, p.codes.length + (p.codes.length === 0 ? 0 : 0));
    assert.equal(p.actuationSupported, false);
    assert.equal(p.guarantee, "NONE");
    assert.equal(p.label, "model, not a command");
    if (p.now.setpointW !== null) {
      seen++;
      assert.ok(p.now.setpointW >= 500 && p.now.setpointW <= limit && p.now.setpointW % 100 === 0, String(p.now.setpointW));
      assert.ok(p.targetSocPct !== null && p.targetSocPct <= 100);
      assert.ok(p.trajectory.length >= 1 && p.trajectory[0]?.setpointW === p.now.setpointW);
      for (const t of p.trajectory) assert.ok(t.setpointW >= 500 && t.setpointW <= limit && t.setpointW % 100 === 0);
      if (p.status === "UNREACHABLE" || p.status === "TARGET_AT_RISK") assert.equal(p.now.setpointW, limit, "best effort is the highest safe rate");
      if (p.expectedFinish !== null) assert.match(p.expectedFinish.wallClock, /^\d\d:\d\d$/);
    }
  }
  assert.ok(seen > 200);
  // the expected finish as a wall clock: window start 00:30 plus 216 minutes is 04:06
  assert.equal(plan({ actuatorProfile: "RATE_CONTROLLER_PROPOSED" }).expectedFinish?.wallClock, "04:06");
});

test("monotone sweeps (seeded): a higher SOC never raises the rate; a higher target, a longer buffer, a later time or a larger capacity never lowers it", () => {
  const r = rng(77);
  for (let i = 0; i < 250; i++) {
    const s = { socPct: 5 + Math.floor(r() * 60), targetSocPct: 50 + Math.floor(r() * 41), bufferMin: 5 * Math.floor(r() * 25), elapsedMin: Math.floor(r() * 120), capacityKwh: 15 + r() * 25 };
    const rate = (o: Partial<GentleNightInput>): number | null => plan({ ...s, ...o }).now.setpointW;
    const at = rate({});
    if (at === null) continue;
    const hi = rate({ socPct: s.socPct + 5 });
    if (hi !== null) assert.ok(hi <= at, "a higher SOC lowered the need " + JSON.stringify(s));
    const tg = rate({ targetSocPct: Math.min(100, s.targetSocPct + 5) });
    if (tg !== null) assert.ok(tg >= at, "a higher target " + JSON.stringify(s));
    const bf = rate({ bufferMin: Math.min(120, s.bufferMin + 15) });
    if (bf !== null) assert.ok(bf >= at, "a longer buffer " + JSON.stringify(s));
    const el = rate({ elapsedMin: s.elapsedMin + 20, socPct: s.socPct });
    if (el !== null) assert.ok(el >= at, "less time left " + JSON.stringify(s));
    const cp = rate({ capacityKwh: s.capacityKwh + 5 });
    if (cp !== null) assert.ok(cp >= at, "a larger capacity " + JSON.stringify(s));
  }
});

test("the explicit taper shape: the pessimistic knee is configurable and an earlier knee or a lower tail only ever raises the rate; a target below the knee ignores both", () => {
  const t90 = plan({ targetSocPct: 85 });
  assert.equal(plan({ targetSocPct: 85, params: { kneeSocPct: 70 } }).now.setpointW as number >= (t90.now.setpointW as number), true);
  assert.equal(plan({ targetSocPct: 85, params: { tailFraction: 0.05, tailFractionExpected: 0.1 } }).now.setpointW, t90.now.setpointW, "below the knee the tail never matters");
  const above = (o: Partial<NonNullable<GentleNightInput["params"]>>): number => plan({ targetSocPct: 93, socPct: 70, params: o }).now.setpointW as number;
  assert.ok(above({ kneeSocPct: 80 }) >= above({}));
  assert.ok(above({ tailFraction: 0.05 }) >= above({}));
  assert.ok(above({ tailFraction: 0.2, tailFractionExpected: 0.25 }) <= above({}));
  assert.ok(above({ kneeSocPct: 95, kneeSpreadPct: 2 }) <= above({}));
  assert.equal(DEFAULT_NIGHT_PARAMS.kneeSocPct, 90);
  assert.ok(DEFAULT_NIGHT_PARAMS.tailFraction < DEFAULT_NIGHT_PARAMS.tailFractionExpected);
  const p = plan({ targetSocPct: 93 });
  const a = p.assumptions as Record<string, number>;
  assert.ok((a.kneePessimisticPct as number) < (a.kneeExpectedPct as number) && (a.kneeExpectedPct as number) <= (a.kneeOptimisticPct as number));
  assert.ok((a.tailPessimistic as number) < (a.tailExpected as number));
});

test("the overshoot allowance is configurable from 1.0 to 1.5 and lowers every converted limit, never a plain setpoint bound", () => {
  const dc = { name: "battery", watts: 6000, basis: "BATTERY_DC" as const };
  const at = (o: number): number | null => plan({ ceilings: [maxChargePowerCeiling(8000, 8000), dc], params: { setpointOvershoot: o } }).now.ceilingW;
  assert.equal(at(1), 6000);
  assert.equal(at(1.1), 5400);
  assert.equal(at(1.5), 4000);
  assert.equal(plan({ params: { setpointOvershoot: 1.5 } }).now.ceilingW, 8000, "the plain bound is a setpoint bound");
  assert.equal(plan({ params: { setpointOvershoot: 0.9 } }).codes[0], "PARAMS_INVALID");
  assert.equal(plan({ params: { setpointOvershoot: 1.6 } }).codes[0], "PARAMS_INVALID");
});

test("the input is never changed, the same input gives the same plan, and garbage never throws", () => {
  const deep = (o: unknown): void => {
    if (o !== null && typeof o === "object") {
      for (const v of Object.values(o as Record<string, unknown>)) deep(v);
      Object.freeze(o);
    }
  };
  const input: GentleNightInput = JSON.parse(JSON.stringify({ ...base, inForce: { setpointW: 4000, lastChangeAtMin: 0, changesUsed: 0 }, previousSoc: { socPct: 19, elapsedMin: -5 }, household: { gridImportLimitW: 9000, demandPeakW: 1500, demandAgeMin: 2 }, actuatorProfile: "RATE_CONTROLLER_PROPOSED" }));
  const before = JSON.stringify(input);
  deep(input);
  const a = planGentleNight(input);
  const b = planGentleNight(input);
  assert.equal(JSON.stringify(input), before);
  assert.deepEqual(a, b);
  const r = rng(5);
  const junk = [null, undefined, NaN, Infinity, -1, 0, "x", [], {}, { a: 1 }, true, () => 1];
  for (let i = 0; i < 400; i++) {
    const o: Record<string, unknown> = { ...base };
    for (const k of Object.keys(o)) if (r() < 0.25) o[k] = junk[Math.floor(r() * junk.length)];
    const p = planGentleNight(o as unknown as GentleNightInput);
    assert.equal(p.actuationSupported, false);
    for (const c of p.codes) assert.ok((NIGHT_CODES as readonly string[]).includes(c));
  }
});

test("static: no service call, write, network, file, clock or randomness; imports only the model, time, settings and the slot type; never exported by the package index; actuationSupported is false everywhere", () => {
  const raw = readFileSync(new URL("../src/gentleNight.ts", import.meta.url), "utf8");
  const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'])\/\/.*$/gm, "$1").replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
  for (const banned of [/callService/, /callWS/, /\bhass\b/i, /\bfetch\s*\(/, /XMLHttpRequest|WebSocket|EventSource|sendBeacon/, /\bDate\b/, /Math\.random/, /performance\.now/, /setTimeout|setInterval/,
    /\bwrite/i, /turn_on|set_value|press|modbus|register/i, /\bimport\s*\(/, /\bclass\s/, /\basync\b|\bawait\b|\bPromise\b/, /\bprocess\b/, /\bwindow\./, /\bdocument\b|\bglobalThis\b/,
    /localStorage|sessionStorage|indexedDB/, /\bthis\b/, /\bnew\s+(Date|Function|Worker)/, /\beval\b/, /require\s*\(/, /\bconsole\./, /node:/, /readFile|writeFile|createWriteStream|\bfs\b/, /\.(set|delete|clear)\s*\(/]) {
    assert.doesNotMatch(code, banned, "matches " + banned);
  }
  const imports = [...raw.matchAll(/^import\s+(?:type\s+)?\{[^}]*\}\s*from\s+"([^"]+)"/gm)].map((m) => m[1]).sort();
  assert.deepEqual(imports, ["./gentleController.ts", "./gentleController.ts", "./settings.ts", "./time.ts", "./time.ts", "./tou.ts"]);
  assert.doesNotMatch(raw, /actuationSupported:\s*true/);
  assert.equal((raw.match(/actuationSupported:\s*false/g) ?? []).length, 3, "the type, the refusal and the plan: all false");
  for (const name of Object.keys(NIGHT_MODULE)) assert.doesNotMatch(name, /^(write|send|call|post|put|set[A-Z]|execute|dispatch|publish|save|push|apply|actuate)/, "export " + name + " sounds like a write");
  const index = readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
  assert.doesNotMatch(index, /gentleNight/, "exporting the night planner from the package index changes the pinned card bundle; add a chain entry first");
});
