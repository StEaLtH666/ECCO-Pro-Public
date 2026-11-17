import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  planGentle, projectCharge, windowRealMinutes, smallestKnownCeiling, acceptanceFraction, powerFromCurrent,
  CONTROLLER_LABEL, ASSUMED_LABEL, ACTUATION_REASON, DEFAULT_GENTLE_PARAMS,
} from "../src/gentleController.ts";
import type { GentleInput, GentleDecision, GentleParams, NamedCeiling, ChargeModel } from "../src/gentleController.ts";
import type { ClockDay } from "../src/time.ts";
import { norm } from "../src/time.ts";
import { rng } from "./fixtures.ts";
import { makeScenario, runClosedLoop, runStatic, feasibility, wallAt, trueFinishMin, readTolerance } from "./support/batterySim.ts";

// ---------------------------------------------------------------------------------------------------------------------------------
// A fixed example: 22:00 to 04:00 (360 min), 60 min buffer (deadline at minute 300), 30 kWh nominal (+6 % band), 20 % -> 80 %.
// ---------------------------------------------------------------------------------------------------------------------------------
const ORDINARY: ClockDay = { changeAtMin: 0, deltaMin: 0 };
const SPRING: ClockDay = { changeAtMin: 120, deltaMin: 60 };
const AUTUMN: ClockDay = { changeAtMin: 120, deltaMin: -60 };
const CEILINGS: NamedCeiling[] = [
  { name: "owner_maximum", watts: 5000 },
  { name: "battery_max_charge", watts: 6200 },
  { name: "grid_charge_current", watts: null },
  { name: "max_grid_charge_power", watts: undefined },
];
const base: GentleInput = {
  targetSocPct: 80, bufferMin: 60, chargeWindow: { startMin: 22 * 60, endMin: 4 * 60, clockDay: ORDINARY }, elapsedMin: 0, socPct: 20, socAgeMin: 1,
  capacityKwh: 30, capacityUpPct: 6, ceilings: CEILINGS, currentSetpointW: null, lastChangeElapsedMin: null, changesUsed: 0,
};
const plan = (over: Partial<GentleInput> = {}) => planGentle({ ...base, ...over });
const P: GentleParams = { ...DEFAULT_GENTLE_PARAMS };
const modelFor = (i: GentleInput, ceilW: number, p: GentleParams = P): ChargeModel => ({
  capacityKwh: Math.max(i.capacityKwh, i.learnedCapacityKwh ?? 0) * (1 + i.capacityUpPct / 100), chargeEff: p.chargeEff, ceilingW: ceilW, taperStartSocPct: p.taperStartSocPct, taperEndFraction: p.taperEndFraction,
});

// ---- the label, the constants, the honest "not supported" ------------------------------------------------------------------------------

test("a decision is labelled 'model, not a command' and never claims actuation", () => {
  const d = plan();
  assert.equal(d.label, CONTROLLER_LABEL);
  assert.equal(CONTROLLER_LABEL, "model, not a command");
  assert.equal(d.assumptionsLabel, ASSUMED_LABEL);
  assert.equal(d.actuationSupported, false);
  assert.match(d.actuationReason, /fixes the Free Power rate at START/);
  assert.equal(d.actuationReason, ACTUATION_REASON);
  assert.equal(d.targetSocPct, 80);
});

test("static: the module has no service call, write, clock or randomness and cannot claim actuation", () => {
  const raw = readFileSync(new URL("../src/gentleController.ts", import.meta.url), "utf8");
  const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'])\/\/.*$/gm, "$1").replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
  for (const banned of [/callService/, /\bhass\b/i, /\bfetch\s*\(/, /\bDate\b/, /Math\.random/, /setTimeout|setInterval/, /\bwrite/i, /turn_on|set_value|press|modbus|register/i, /\bimport\s*\(/, /\bclass\s/, /\basync\b|\bawait\b|\bPromise\b/, /\bprocess\b/, /\bwindow\b|\bdocument\b|\bglobalThis\b/, /localStorage|sessionStorage|indexedDB/]) {
    assert.doesNotMatch(code, banned, "matches " + banned);
  }
  const imports = [...code.matchAll(/^import\s+(?:type\s+)?\{[^}]*\}\s*from\s+""/gm)];
  assert.equal(imports.length, 3, "imports only time.ts and settings.ts");
  assert.deepEqual([...raw.matchAll(/^import\s+(?:type\s+)?\{[^}]*\}\s*from\s+"([^"]+)"/gm)].map((m) => m[1]).sort(), ["./settings.ts", "./time.ts", "./time.ts"]);
  assert.doesNotMatch(raw, /actuationSupported:\s*true/);
  assert.equal((raw.match(/actuationSupported:\s*false/g) ?? []).length, 2, "the type and the one place it is set, both false");
});

// ---- the lowest step -------------------------------------------------------------------------------------------------------------

test("the setpoint is the lowest 100 W step that reaches the target by the deadline (hand-checked, and a linear search agrees)", () => {
  const d = plan();
  assert.equal(d.status, "OK");
  // (80 - 19.5) % of 31.8 kWh = 19.239 kWh, / 0.95 = 20.252 kWh grid side, over 300 min = 4050 W -> 4100 W.
  assert.equal(d.neededW, 4100);
  assert.equal(d.setpointW, 4100);
  assert.equal(d.change, "START");
  assert.equal(d.changeRecommended, true);
  assert.equal(d.ceilingW, 5000);
  assert.equal(d.ceilingName, "owner_maximum");
  assert.ok(d.finishInMin !== null && d.finishInMin <= 300 && d.marginMin !== null && d.marginMin >= 0);
  const m = modelFor(base, 5000);
  assert.ok(projectCharge(19.5, 4100, 80, m, 300).finishMin !== null);
  assert.equal(projectCharge(19.5, 4000, 80, m, 300).finishMin, null, "the step below would finish late");
  // linear search over every step equals the controller's answer, on random states
  const rand = rng(515);
  let checked = 0;
  for (let n = 0; n < 800; n++) {
    const i: GentleInput = { ...base, targetSocPct: [80, 90, 100][Math.floor(rand() * 3)] as number, socPct: 5 + Math.floor(rand() * 80), elapsedMin: Math.floor(rand() * 200), bufferMin: 5 * Math.floor(rand() * 25), capacityKwh: 15 + rand() * 30, ceilings: [{ name: "owner_maximum", watts: 2500 + Math.floor(rand() * 5500) }] };
    const out = planGentle(i);
    if (out.neededW === null) continue;
    checked++;
    const ceilW = out.ceilingW as number;
    const avail = (out.deadlineInMin as number) - (i.targetSocPct >= 100 ? P.topHoldMin : 0);
    const soc = (i.socPct as number) - P.socResolutionPct / 2;
    const mm = modelFor(i, ceilW);
    let first: number | null = null;
    for (let w = 500; w <= ceilW; w += 100) if (projectCharge(soc, w, i.targetSocPct, mm, avail).finishMin !== null) { first = w; break; }
    assert.equal(out.neededW, first, JSON.stringify([i.targetSocPct, i.socPct, i.elapsedMin, i.bufferMin]));
  }
  assert.ok(checked > 250, "enough feasible random states: " + checked);
});

test("the pessimistic capacity: the band and the larger of nominal and learned raise the setpoint; a smaller learned value is ignored", () => {
  const nominalOnly = plan({ capacityUpPct: 0 }).neededW as number;
  const withBand = plan().neededW as number;
  assert.ok(withBand > nominalOnly, "the +6 % band needs more power: " + withBand + " vs " + nominalOnly);
  const learnedBig = plan({ learnedCapacityKwh: 33 }).neededW as number;
  assert.ok(learnedBig > withBand, "a larger learned capacity is used");
  assert.equal(plan({ learnedCapacityKwh: 25 }).neededW, withBand, "a smaller learned capacity does not lower the plan");
  assert.equal(plan({ learnedCapacityKwh: null }).neededW, withBand);
});

test("the BMS taper and the top-of-charge hold: a 100 % target needs more than 90 %, the hold applies only at 100, taper_dropped needs less", () => {
  const roomy = { socPct: 40, ceilings: [{ name: "owner_maximum", watts: 8000 }] } as Partial<GentleInput>;
  const t90 = plan({ ...roomy, targetSocPct: 90 }).neededW as number;
  const t100 = plan({ ...roomy, targetSocPct: 100 }).neededW as number;
  assert.ok(t100 > t90 + 500, "a 100 % target costs more power: " + t100 + " vs " + t90);
  const noHold = plan({ ...roomy, targetSocPct: 100, params: { topHoldMin: 0 } }).neededW as number;
  assert.ok(noHold < t100, "the hold costs power at 100 %");
  assert.equal(plan({ ...roomy, targetSocPct: 90, params: { topHoldMin: 60 } }).neededW, t90, "the hold does not apply below 100 %");
  const noTaper = plan({ ...roomy, targetSocPct: 100, params: { taperEndFraction: 1 } }).neededW as number;
  assert.ok(noTaper < t100, "dropping the taper lowers the plan: " + noTaper + " vs " + t100);
  const harsh = plan({ ...roomy, targetSocPct: 100, params: { taperStartSocPct: 80, taperEndFraction: 0.05 } });
  assert.ok(harsh.neededW === null || (harsh.neededW as number) > t100, "a harsher assumed taper raises it");
  assert.equal(acceptanceFraction(85, 90, 0.15), 1);
  assert.equal(acceptanceFraction(90, 90, 0.15), 1);
  assert.ok(Math.abs(acceptanceFraction(95, 90, 0.15) - 0.575) < 1e-9);
  assert.ok(Math.abs(acceptanceFraction(100, 90, 0.15) - 0.15) < 1e-12);
});

// ---- safe ceilings ---------------------------------------------------------------------------------------------------------------

test("the ceiling is the smallest KNOWN one; unknown ones are ignored; none known is NO_SAFE_CEILING and never a guessed default", () => {
  assert.deepEqual(smallestKnownCeiling([{ name: "a", watts: 6000 }, { name: "b", watts: 4300 }, { name: "c", watts: null }, { name: "d", watts: NaN }, { name: "e", watts: -5 }]), { watts: 4300, name: "b" });
  assert.equal(smallestKnownCeiling([{ name: "a", watts: undefined }]), null);
  const d = plan({ ceilings: [{ name: "a", watts: 6000 }, { name: "b", watts: 4350 }, { name: "c", watts: 9000 }] });
  assert.equal(d.ceilingW, 4300, "rounded DOWN to a step");
  assert.equal(d.ceilingName, "b");
  assert.ok((d.setpointW as number) <= 4300);
  assert.equal(plan({ ceilings: [{ name: "a", watts: 20000 }] }).ceilingW, 8000, "capped at the editor maximum");
  for (const none of [[], [{ name: "a", watts: null }], [{ name: "a", watts: undefined }, { name: "b", watts: NaN }], [{ name: "a", watts: -1 }]] as NamedCeiling[][]) {
    const x = plan({ ceilings: none });
    assert.equal(x.status, "NO_SAFE_CEILING");
    assert.equal(x.setpointW, null);
    assert.equal(x.neededW, null);
    assert.equal(x.changeRecommended, false);
    assert.match(x.reasons.join(" "), /no default is guessed/);
  }
  const tiny = plan({ ceilings: [{ name: "grid_charge_current", watts: 400 }, { name: "owner_maximum", watts: 5000 }] });
  assert.equal(tiny.status, "NO_SAFE_CEILING");
  assert.equal(tiny.setpointW, null);
  assert.match(tiny.reasons.join(" "), /below the minimum setpoint/);
  assert.equal(plan({ ceilings: [{ name: "a", watts: 0 }] }).status, "NO_SAFE_CEILING", "a known zero is a ceiling of zero: nothing is recommended");
  assert.equal(powerFromCurrent(60, 51.2), 3072);
  assert.equal(powerFromCurrent(null, 51.2), null);
  assert.equal(powerFromCurrent(60, 0), null);
  assert.equal(powerFromCurrent(-1, 50), null);
});

test("a setpoint in force above a ceiling that has fallen is lowered at once, whatever the dwell, hysteresis or budget", () => {
  const d = plan({ currentSetpointW: 4800, lastChangeElapsedMin: 0, elapsedMin: 1, changesUsed: 6, ceilings: [{ name: "battery_max_charge", watts: 4000 }] });
  assert.equal(d.change, "DECREASE");
  assert.equal(d.changeRecommended, true);
  assert.ok((d.setpointW as number) <= 4000);
  assert.ok(d.codes.includes("ABOVE_CEILING"));
  assert.equal(d.changesUsed, 6, "a safety decrease does not draw on the budget");
});

// ---- data and statuses -----------------------------------------------------------------------------------------------------------

test("unknown or stale SOC is NO_DATA with no setpoint, at every age and value", () => {
  for (const x of [{ socPct: null }, { socPct: NaN }, { socPct: 101 }, { socPct: -1 }, { socAgeMin: null }, { socAgeMin: 16 }, { socAgeMin: 600 }, { socAgeMin: -1 }, { socAgeMin: NaN }] as Partial<GentleInput>[]) {
    const d = plan(x);
    assert.equal(d.status, "NO_DATA", JSON.stringify(x));
    assert.equal(d.setpointW, null);
    assert.equal(d.neededW, null);
    assert.equal(d.changeRecommended, false);
  }
  assert.equal(plan({ socAgeMin: 15 }).status, "OK", "exactly the limit is still fresh");
  assert.equal(plan({ socAgeMin: 0 }).status, "OK");
  assert.equal(plan({ socAgeMin: 30, params: { maxSocAgeMin: 45 } }).status, "OK", "the limit is the owner's parameter");
});

test("SOC at or above the target is NOTHING_TO_CHARGE, one point below is not", () => {
  for (const [target, soc] of [[80, 80], [80, 95], [90, 90], [100, 100], [10, 10]] as const) {
    const d = plan({ targetSocPct: target, socPct: soc });
    assert.equal(d.status, "NOTHING_TO_CHARGE", target + "/" + soc);
    assert.equal(d.setpointW, null);
    assert.equal(d.targetSocPct, target);
  }
  for (const [target, soc] of [[80, 79], [90, 89], [100, 99], [100, 99.9]] as const) assert.notEqual(plan({ targetSocPct: target, socPct: soc }).status, "NOTHING_TO_CHARGE", target + "/" + soc);
  assert.equal(plan({ targetSocPct: 100, socPct: 99 }).status, "OK");
});

test("the deadline passed is DEADLINE_PASSED: the buffer is not hidden, the target is not lowered, the ceiling is the best effort while the window is open", () => {
  const atDeadline = plan({ elapsedMin: 300 });
  assert.equal(atDeadline.status, "DEADLINE_PASSED");
  assert.equal(atDeadline.targetSocPct, 80);
  assert.equal(atDeadline.setpointW, 5000, "inside the buffer: the safe ceiling, nothing above it");
  assert.match(atDeadline.reasons.join(" "), /deadline has passed/);
  assert.notEqual(plan({ elapsedMin: 299 }).status, "DEADLINE_PASSED", "one minute before the deadline it is still a plan (here an unreachable one)");
  assert.equal(plan({ elapsedMin: 299, socPct: 79.9 }).targetSocPct, 80);
  const pastEnd = plan({ elapsedMin: 360 });
  assert.equal(pastEnd.status, "DEADLINE_PASSED");
  assert.equal(pastEnd.setpointW, null, "the window is over: no recommendation");
  const whole = plan({ bufferMin: 120, chargeWindow: { startMin: 0, endMin: 120, clockDay: ORDINARY } });
  assert.equal(whole.status, "DEADLINE_PASSED");
  assert.ok(whole.codes.includes("BUFFER_AS_LONG_AS_WINDOW"));
  assert.match(whole.reasons.join(" "), /buffer .* as long as/);
});

test("INVALID inputs are named and recommend nothing", () => {
  const bad: Partial<GentleInput>[] = [
    { targetSocPct: 9 }, { targetSocPct: 101 }, { targetSocPct: NaN }, { bufferMin: 7 }, { bufferMin: 125 }, { bufferMin: -5 }, { capacityKwh: 0 }, { capacityUpPct: -1 },
    { learnedCapacityKwh: -3 }, { elapsedMin: -1 }, { elapsedMin: NaN }, { chargeWindow: { startMin: 60, endMin: 60, clockDay: ORDINARY } }, { currentSetpointW: -100 },
    { lastChangeElapsedMin: 50, elapsedMin: 10 }, { changesUsed: 1.5 }, { changesUsed: -1 },
    { params: { replanMin: 4 } }, { params: { replanMin: 16 } }, { params: { stepW: 0 } }, { params: { chargeEff: 1.2 } }, { params: { taperEndFraction: 0 } }, { params: { taperStartSocPct: 100 } },
    { params: { minW: 50 } }, { params: { hysteresisW: -1 } }, { params: { maxChanges: -1 } }, { params: { dwellMin: NaN } },
  ];
  for (const x of bad) {
    const d = plan(x);
    assert.equal(d.status, "INVALID", JSON.stringify(x));
    assert.equal(d.setpointW, null);
    assert.equal(d.changeRecommended, false);
    assert.equal(d.actuationSupported, false);
  }
  assert.equal(planGentle(undefined as unknown as GentleInput).status, "INVALID");
  assert.equal(plan({ targetSocPct: 10, socPct: 5 }).status, "OK", "10 is allowed");
  assert.equal(plan({ targetSocPct: 100, socPct: 80, ceilings: [{ name: "owner_maximum", watts: 8000 }] }).status, "OK", "100 is allowed");
  assert.equal(plan({ bufferMin: 0 }).status, "OK");
  assert.equal(plan({ bufferMin: 120, socPct: 35 }).status, "OK");
});

// ---- the target is never lowered, a too-small buffer is reported -----------------------------------------------------------------

test("a buffer too small is TARGET_AT_RISK (finishes late inside the buffer) or TARGET_UNREACHABLE; both say so, clip at the ceiling and keep the target", () => {
  // 40 % -> 100 %, 5000 W ceiling, 6 h window: the ceiling finishes inside the window but not 60 minutes early -> AT_RISK
  const riskIn: Partial<GentleInput> = { targetSocPct: 100, socPct: 40, bufferMin: 60 };
  const risk = plan(riskIn);
  assert.equal(risk.status, "TARGET_AT_RISK");
  assert.equal(risk.neededW, null);
  assert.equal(risk.setpointW, 5000);
  assert.equal(risk.targetSocPct, 100);
  assert.match(risk.reasons.join(" "), /Buffer too small/);
  assert.match(risk.reasons.join(" "), /not lowered/);
  assert.match(risk.reasons.join(" "), /late, inside the buffer/);
  assert.ok(risk.suggestedBufferMin !== null && risk.suggestedBufferMin < 60, "a smaller buffer is suggested: " + risk.suggestedBufferMin);
  assert.ok(risk.marginMin !== null && risk.marginMin < 0, "the projected margin to the deadline is negative");
  assert.equal(plan({ ...riskIn, bufferMin: risk.suggestedBufferMin as number }).status, "OK", "the suggested buffer absorbs it");
  const un = plan({ targetSocPct: 100, bufferMin: 0, chargeWindow: { startMin: 22 * 60, endMin: 1 * 60, clockDay: ORDINARY } });
  assert.equal(un.status, "TARGET_UNREACHABLE");
  assert.equal(un.setpointW, 5000);
  assert.equal(un.targetSocPct, 100);
  assert.equal(un.finishInMin, null);
  assert.match(un.reasons.join(" "), /Buffer too small, or the target is out of reach/);
  assert.match(un.reasons.join(" "), /not lowered/);
  for (const d of [risk, un]) assert.ok((d.setpointW as number) <= (d.ceilingW as number));
});

// ---- hysteresis, dwell, increases, budget ----------------------------------------------------------------------------------------

test("a decrease needs the dwell and a saving of at least the hysteresis; the time slack stops it going too low", () => {
  const at = (w: number, over: Partial<GentleInput> = {}) => plan({ currentSetpointW: w, lastChangeElapsedMin: 0, elapsedMin: 100, socPct: 45, ...over });
  const probe = at(5000);
  const down = probe.setpointW as number;
  assert.ok(probe.neededW !== null && down >= (probe.neededW as number));
  // dwell: 100 minutes since the last change -> a decrease is allowed
  assert.equal(probe.change, "DECREASE");
  assert.ok(probe.codes.includes("DECREASE_SAVING"));
  assert.ok(5000 - down >= 500, "saves at least the hysteresis");
  // dwell not elapsed (29 min since the change): held
  const dwell = at(5000, { lastChangeElapsedMin: 71 });
  assert.equal(dwell.change, "NONE");
  assert.equal(dwell.setpointW, 5000);
  assert.ok(dwell.codes.includes("HELD_DWELL"));
  assert.equal(at(5000, { lastChangeElapsedMin: 70 }).change, "DECREASE", "exactly the dwell is enough");
  // hysteresis: a setpoint only a little above the decrease target is kept
  const near = at(down + 300);
  assert.equal(near.change, "NONE");
  assert.ok(near.codes.includes("HELD_HYSTERESIS"));
  assert.equal(near.setpointW, down + 300);
  assert.equal(at(down + 500).change, "DECREASE", "a saving of exactly the hysteresis is enough");
  assert.equal(at(down + 500, { params: { hysteresisW: 600 } }).change, "NONE");
  // slack: a setpoint between the needed step and the slack level is kept
  const needed = probe.neededW as number;
  if (down > needed) {
    const slack = at(needed + 100);
    assert.equal(slack.change, "NONE");
    assert.equal(slack.setpointW, needed + 100);
  }
  // a setpoint in force that equals the need is unchanged
  const same = at(needed);
  assert.equal(same.change, "NONE");
  assert.ok(same.codes.includes("UNCHANGED"));
  // no change history: the dwell is not in the way
  assert.equal(at(5000, { lastChangeElapsedMin: null }).change, "DECREASE");
});

test("an INCREASE needed to make the deadline is never held back by dwell or hysteresis (a 100 W increase right after a change goes through)", () => {
  const late = plan({ currentSetpointW: 3000, lastChangeElapsedMin: 99, elapsedMin: 100, socPct: 35 });
  assert.equal(late.change, "INCREASE");
  assert.equal(late.changeRecommended, true);
  assert.equal(late.setpointW, late.neededW);
  assert.ok((late.setpointW as number) > 3000);
  assert.ok(late.codes.includes("INCREASE_FOR_DEADLINE"));
  assert.equal(late.changesUsed, 1);
  assert.equal(late.status, "OK");
  const needed = late.neededW as number;
  const small = plan({ currentSetpointW: needed - 100, lastChangeElapsedMin: 100, elapsedMin: 100, socPct: 35 });
  assert.equal(small.change, "INCREASE", "a 100 W increase is under the hysteresis and inside the dwell, and still happens");
  assert.equal(small.setpointW, needed);
  const dwell0 = plan({ currentSetpointW: needed - 100, lastChangeElapsedMin: 100, elapsedMin: 100, socPct: 35, params: { dwellMin: 120, hysteresisW: 5000 } });
  assert.equal(dwell0.change, "INCREASE");
});

test("the changes budget: the START is free, increases and decreases draw on it, an exhausted budget holds the setpoint and says what it costs", () => {
  const start = plan({ changesUsed: 6 });
  assert.equal(start.change, "START", "the first setpoint is not a change");
  assert.equal(start.changesUsed, 6);
  const inc = plan({ currentSetpointW: 3000, socPct: 35, elapsedMin: 100, changesUsed: 5, lastChangeElapsedMin: 0 });
  assert.equal(inc.change, "INCREASE");
  assert.equal(inc.changesUsed, 6);
  assert.equal(inc.changesLeft, 0);
  const held = plan({ currentSetpointW: 3000, socPct: 35, elapsedMin: 100, changesUsed: 6, lastChangeElapsedMin: 0 });
  assert.equal(held.change, "NONE");
  assert.equal(held.setpointW, 3000);
  assert.ok(held.codes.includes("HELD_BUDGET"));
  assert.equal(held.status, "TARGET_AT_RISK", "the held setpoint would finish late");
  assert.ok(held.marginMin === null || held.marginMin < 0);
  const dec = plan({ currentSetpointW: 5000, socPct: 45, elapsedMin: 100, changesUsed: 6, lastChangeElapsedMin: 0 });
  assert.equal(dec.change, "NONE");
  assert.ok(dec.codes.includes("HELD_BUDGET"));
  assert.equal(dec.status, "OK");
  assert.equal(plan({ currentSetpointW: 5000, socPct: 45, elapsedMin: 100, changesUsed: 5, lastChangeElapsedMin: 0 }).change, "DECREASE");
  assert.equal(plan({ currentSetpointW: 5000, socPct: 45, elapsedMin: 100, changesUsed: 1, lastChangeElapsedMin: 0, params: { maxChanges: 1 } }).change, "NONE");
});

// ---- time: real minutes across a clock change ------------------------------------------------------------------------------------

test("the window length and the deadline use real elapsed minutes: 23 h and 25 h days", () => {
  assert.equal(windowRealMinutes(22 * 60, 4 * 60, ORDINARY), 360);
  assert.equal(windowRealMinutes(22 * 60, 4 * 60, SPRING), 300, "the clock skips an hour: 5 real hours");
  assert.equal(windowRealMinutes(22 * 60, 4 * 60, AUTUMN), 420, "the clock repeats an hour: 7 real hours");
  assert.equal(windowRealMinutes(60, 60, ORDINARY), null);
  assert.equal(windowRealMinutes(NaN, 60, ORDINARY), null);
  const o = plan({ socPct: 35 });
  const s = plan({ socPct: 35, chargeWindow: { startMin: 22 * 60, endMin: 4 * 60, clockDay: SPRING } });
  const a = plan({ socPct: 35, chargeWindow: { startMin: 22 * 60, endMin: 4 * 60, clockDay: AUTUMN } });
  assert.equal(o.deadlineInMin, 300);
  assert.equal(s.deadlineInMin, 240);
  assert.equal(a.deadlineInMin, 360);
  assert.ok((s.neededW as number) > (o.neededW as number), "a 23 h night has less time: a higher setpoint");
  assert.ok((a.neededW as number) < (o.neededW as number), "a 25 h night has more time: a lower setpoint");
  assert.equal(s.windowEndInMin, 300);
  assert.equal(plan({ chargeWindow: { startMin: 22 * 60, endMin: 4 * 60, clockDay: SPRING }, elapsedMin: 240 }).status, "DEADLINE_PASSED");
  assert.equal(plan({ chargeWindow: { startMin: 22 * 60, endMin: 4 * 60, clockDay: AUTUMN }, elapsedMin: 300, socPct: 75 }).status, "OK");
  // a change after the window does not touch it
  assert.equal(plan({ chargeWindow: { startMin: 22 * 60, endMin: 1 * 60, clockDay: { changeAtMin: 180, deltaMin: 60 } } }).deadlineInMin, 120);
});

test("the simulator's own real-minute mapping agrees with the controller's window length on every clock-change scenario", () => {
  let spring = 0;
  let autumn = 0;
  for (let id = 0; id < 400; id++) {
    const sc = makeScenario(id);
    const end = norm(sc.windowStartMin + sc.windowWallMin);
    assert.equal(windowRealMinutes(sc.windowStartMin, end, sc.clockDay), sc.windowRealMin);
    assert.equal(wallAt(sc, sc.windowRealMin), end, "real minute " + sc.windowRealMin + " is wall " + end + " (scenario " + id + ")");
    if (sc.clockDay.deltaMin === 60) { spring++; assert.equal(sc.windowRealMin, sc.windowWallMin - 60); }
    if (sc.clockDay.deltaMin === -60) { autumn++; assert.equal(sc.windowRealMin, sc.windowWallMin + 60); }
  }
  assert.ok(spring >= 30 && autumn >= 30, "clock-change days exercised: " + spring + " spring, " + autumn + " autumn");
});

// ---- properties over random inputs -----------------------------------------------------------------------------------------------

function randomInput(rand: () => number): GentleInput {
  const pickN = <T>(xs: readonly T[]): T => xs[Math.floor(rand() * xs.length)] as T;
  const day = pickN([ORDINARY, ORDINARY, SPRING, AUTUMN]);
  const wall = 5 * (36 + Math.floor(rand() * 85));
  const start = day.deltaMin === 0 ? 5 * Math.floor(rand() * 288) : norm(120 - 5 * (6 + Math.floor(rand() * (wall / 5 - 12))));
  const elapsed = Math.floor(rand() * (wall + 30));
  const named = ["owner_maximum", "battery_max_charge", "grid_charge_current", "max_grid_charge_power"];
  const ceilings: NamedCeiling[] = named.map((name) => ({ name, watts: rand() < 0.35 ? pickN([null, undefined, NaN, -1]) : 300 + Math.floor(rand() * 9000) }));
  const cur = rand() < 0.3 ? null : 100 * Math.floor(5 + rand() * 75);
  return {
    targetSocPct: pickN([10, 50, 80, 90, 95, 100]), bufferMin: 5 * Math.floor(rand() * 25),
    chargeWindow: { startMin: start, endMin: norm(start + wall), clockDay: day }, elapsedMin: elapsed,
    socPct: rand() < 0.08 ? null : Math.round(rand() * 1000) / 10, socAgeMin: rand() < 0.1 ? Math.floor(rand() * 40) : Math.floor(rand() * 10),
    capacityKwh: 10 + rand() * 40, capacityUpPct: Math.floor(rand() * 12), learnedCapacityKwh: rand() < 0.4 ? 10 + rand() * 45 : null, ceilings,
    currentSetpointW: cur, lastChangeElapsedMin: cur === null || rand() < 0.3 ? null : Math.floor(rand() * elapsed), changesUsed: Math.floor(rand() * 9),
    params: rand() < 0.3 ? { dwellMin: pickN([0, 15, 30, 60]), hysteresisW: pickN([0, 300, 500, 900]), maxChanges: pickN([0, 2, 6]), topHoldMin: pickN([0, 20, 40]), decreaseSlackMin: pickN([0, 15, 30]) } : undefined,
  };
}

const knownMin = (c: readonly NamedCeiling[]) => Math.min(...c.filter((x) => typeof x.watts === "number" && Number.isFinite(x.watts) && x.watts >= 0).map((x) => x.watts as number));

test("property (6000 random inputs): never above a known ceiling, always a step multiple, the target is never lowered, no recommendation without data or ceiling", () => {
  const rand = rng(20261117);
  const seen: Record<string, number> = {};
  for (let n = 0; n < 6000; n++) {
    const i = randomInput(rand);
    const before = JSON.stringify(i);
    const d = planGentle(i);
    assert.equal(JSON.stringify(i), before, "the input is not mutated");
    seen[d.status] = (seen[d.status] ?? 0) + 1;
    assert.equal(d.targetSocPct, i.targetSocPct, "the target is never changed");
    assert.equal(d.label, CONTROLLER_LABEL);
    assert.equal(d.actuationSupported, false);
    const w = d.setpointW;
    const p = { ...DEFAULT_GENTLE_PARAMS, ...(i.params ?? {}) };
    if (w !== null) {
      assert.equal(w % p.stepW, 0, "a multiple of the step: " + w);
      assert.ok(w >= p.minW, "at least the minimum: " + w);
      assert.ok(w <= knownMin(i.ceilings), "never above the smallest known ceiling: " + w + " vs " + knownMin(i.ceilings));
      assert.ok(w <= p.hardMaxW);
      assert.ok(d.ceilingW !== null && w <= d.ceilingW);
      assert.ok(d.status !== "NO_DATA" && d.status !== "NO_SAFE_CEILING" && d.status !== "INVALID" && d.status !== "NOTHING_TO_CHARGE");
    }
    if (d.status === "NO_DATA" || d.status === "NO_SAFE_CEILING" || d.status === "INVALID" || d.status === "NOTHING_TO_CHARGE") {
      assert.equal(d.setpointW, null);
      assert.equal(d.changeRecommended, false);
      assert.equal(d.neededW, null);
    }
    if (d.status === "NO_DATA") assert.ok(i.socPct === null || !(i.socPct >= 0 && i.socPct <= 100) || i.socAgeMin === null || i.socAgeMin > p.maxSocAgeMin);
    if (d.status === "NO_SAFE_CEILING") assert.ok(!Number.isFinite(knownMin(i.ceilings)) || knownMin(i.ceilings) < p.minW);
    if (d.status === "NOTHING_TO_CHARGE") assert.ok((i.socPct as number) >= i.targetSocPct);
    assert.equal(d.changeRecommended, d.change !== "NONE");
    if (d.change === "INCREASE") assert.ok((d.setpointW as number) > (i.currentSetpointW as number));
    if (d.change === "DECREASE") assert.ok((d.setpointW as number) < (i.currentSetpointW as number));
    if (d.change === "START") assert.ok(i.currentSetpointW === null || i.currentSetpointW <= 0);
    if (d.neededW !== null) assert.ok((d.ceilingW as number) >= d.neededW && d.neededW % p.stepW === 0);
    if (d.status === "TARGET_AT_RISK" || d.status === "TARGET_UNREACHABLE") assert.match(d.reasons.join(" "), /not lowered/);
    if (d.status === "TARGET_UNREACHABLE") assert.equal(d.finishInMin, null);
    for (let k = 1; k < d.trajectory.length; k++) {
      assert.ok((d.trajectory[k] as { socPct: number }).socPct >= (d.trajectory[k - 1] as { socPct: number }).socPct - 1e-9, "the trajectory never falls");
      assert.ok((d.trajectory[k] as { socPct: number }).socPct <= 100 + 1e-9);
    }
    if (d.finishInMin !== null && d.deadlineInMin !== null) assert.ok(Math.abs((d.marginMin as number) - (d.deadlineInMin - (i.targetSocPct >= 100 ? p.topHoldMin : 0) - d.finishInMin)) < 0.11);
    assert.ok(d.changesUsed >= i.changesUsed && d.changesUsed <= i.changesUsed + 1);
  }
  for (const s of ["OK", "NOTHING_TO_CHARGE", "TARGET_AT_RISK", "TARGET_UNREACHABLE", "NO_DATA", "NO_SAFE_CEILING", "DEADLINE_PASSED", "INVALID"]) assert.ok((seen[s] ?? 0) > 0 || s === "INVALID", "status exercised: " + s);
});

test("property: more time never raises the setpoint, more SOC never raises it, a higher ceiling never makes it worse", () => {
  const rand = rng(777);
  let compared = 0;
  for (let n = 0; n < 1500; n++) {
    const i = { ...randomInput(rand), currentSetpointW: null, lastChangeElapsedMin: null, socPct: 5 + Math.floor(rand() * 80), socAgeMin: 1, params: undefined, learnedCapacityKwh: null } as GentleInput;
    i.ceilings = [{ name: "owner_maximum", watts: 3000 + Math.floor(rand() * 5000) }];
    i.elapsedMin = Math.floor(rand() * 150);
    i.chargeWindow = { startMin: 22 * 60, endMin: 4 * 60, clockDay: ORDINARY };
    const a = planGentle(i);
    if (a.status !== "OK" && a.status !== "TARGET_AT_RISK" && a.status !== "TARGET_UNREACHABLE") continue;
    const rank = (d: GentleDecision) => (d.status === "OK" ? 0 : d.status === "TARGET_AT_RISK" ? 1 : 2);
    // more time: a shorter buffer (a later deadline)
    if (i.bufferMin >= 5) {
      const b = planGentle({ ...i, bufferMin: i.bufferMin - 5 });
      assert.ok(b.setpointW !== null && a.setpointW !== null && b.setpointW <= a.setpointW, "more time: " + b.setpointW + " <= " + a.setpointW);
      assert.ok(rank(b) <= rank(a), "more time never makes the status worse");
      compared++;
    }
    // more time: a longer window
    const c = planGentle({ ...i, chargeWindow: { startMin: 22 * 60, endMin: 4 * 60 + 30, clockDay: ORDINARY } });
    assert.ok(c.setpointW !== null && a.setpointW !== null && c.setpointW <= a.setpointW, "a longer window: " + c.setpointW + " <= " + a.setpointW);
    // more SOC
    const e = planGentle({ ...i, socPct: (i.socPct as number) + 1 });
    if (e.setpointW !== null) assert.ok(e.setpointW <= (a.setpointW as number), "more SOC: " + e.setpointW + " <= " + a.setpointW);
    // a higher ceiling never raises the lowest step and never worsens the status
    const f = planGentle({ ...i, ceilings: [{ name: "owner_maximum", watts: (i.ceilings[0] as NamedCeiling).watts as number + 1000 }] });
    assert.ok(rank(f) <= rank(a));
    if (a.neededW !== null) assert.equal(f.neededW === null ? Infinity : f.neededW <= a.neededW + 0, true, "a higher ceiling does not raise the lowest step beyond the taper's reference effect");
  }
  assert.ok(compared > 600, "enough comparisons: " + compared);
});

test("the README names every parameter default of the controller model", () => {
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  assert.match(readme, /model, not a command/);
  assert.match(readme, /not supported/i);
  for (const [k, v] of Object.entries(DEFAULT_GENTLE_PARAMS)) {
    const row = readme.split(/\r?\n/).find((l) => l.includes("`" + k + "`"));
    assert.ok(row, "README row for " + k);
    assert.ok((row as string).includes(String(v)), k + " default " + v + " in its README row");
  }
});

// ---- the closed-loop simulator ---------------------------------------------------------------------------------------------------

test("simulator sanity: constant power, no taper, closed-form time (a broken simulator would make every result below meaningless)", () => {
  const sc = { ...makeScenario(1), nominalKwh: 30, trueCapacityKwh: 30, trueEff: 0.95, trueTaper: { startSocPct: 99.9, endFraction: 1 }, ceilW: 8000, startSocPct: 20, targetSocPct: 70, dips: [] };
  const t = trueFinishMin(sc, 3000) as number;
  assert.ok(Math.abs(t - (15 / (3 * 0.95)) * 60) <= 1.01, "15 kWh at 3000 W x 0.95: " + t);
  const slow = trueFinishMin({ ...sc, ceilW: 3000, trueTaper: { startSocPct: 30, endFraction: 0.2 } }, 3000) as number;
  assert.ok(slow > t + 5, "a taper costs time");
  assert.equal(trueFinishMin({ ...sc, ceilW: 1000 }, 8000) as number > 2 * t, true, "the ceiling limits delivery");
});

test("closed loop: at least 300 seeded scenarios; reaching the target, the safety rules, no hiding of what the true battery cannot do", () => {
  const N = 400;
  const cats: Record<string, number> = {};
  let marginDefault = 0;
  let marginReached = 0;
  let marginVariedReached = 0;
  let marginVaried = 0;
  let marginByEnd = 0;
  let marginAll = 0;
  let notFlagged = 0;
  let cannot = 0;
  let strictMiss = 0;
  let worstLate = -Infinity;
  let rules = 0;
  let reversalScenarios = 0;
  let calmReversal = 0;
  let calm = 0;
  let maxReversals = 0;
  let incChecked = 0;
  const targets = new Set<number>();
  const buffers = new Set<number>();
  const dyn: number[] = [];
  const sta: number[] = [];
  let both = 0;
  let dynNoLater = 0;
  let dynReachCount = 0;
  let staReachCount = 0;
  const peakDyn: number[] = [];
  const peakSta: number[] = [];
  const peakRatio: number[] = [];

  for (let id = 0; id < N; id++) {
    const sc = makeScenario(id);
    const run = runClosedLoop(sc);
    const f = feasibility(sc);
    cats[sc.kind + "/" + f] = (cats[sc.kind + "/" + f] ?? 0) + 1;
    targets.add(sc.targetSocPct);
    buffers.add(sc.bufferMin);
    const p = { ...DEFAULT_GENTLE_PARAMS, replanMin: sc.replanMin, ...sc.params };
    const tol = readTolerance(sc);
    assert.equal(run.ticks.length > 0, true);

    // rules, every tick and every change
    for (const tk of run.ticks) {
      const d = tk.decision;
      assert.equal(d.targetSocPct, sc.targetSocPct, "the target is never lowered");
      assert.equal(d.actuationSupported, false);
      if (d.setpointW !== null) {
        assert.equal(d.setpointW % p.stepW, 0, "a step multiple");
        assert.ok(d.setpointW <= (d.ceilingW as number) && (d.ceilingW as number) <= sc.ceilW, "never above the ceiling: " + d.setpointW + " " + d.ceilingW + " " + sc.ceilW);
        assert.ok(d.setpointW >= p.minW);
      }
      if (d.status === "NO_DATA") assert.equal(d.setpointW, null, "stale data: no setpoint");
      // an increase needed for the deadline is never held back by dwell or hysteresis (only by an exhausted budget)
      if (tk.appliedBefore !== null && tk.appliedBefore > 0 && d.neededW !== null && d.neededW > tk.appliedBefore && tk.usedBefore < p.maxChanges) {
        incChecked++;
        assert.equal(d.change, "INCREASE", "scenario " + id + " t=" + tk.t);
        assert.equal(d.setpointW, d.neededW);
      }
      if (d.status === "NOTHING_TO_CHARGE") assert.equal(d.setpointW, null);
      rules++;
    }
    let ordinary = 0;
    let reversals = 0;
    for (let k = 0; k < run.changes.length; k++) {
      const c = run.changes[k] as (typeof run.changes)[number];
      assert.ok(c.toW <= sc.ceilW);
      if (c.kind !== "START") ordinary++;
      if (c.kind === "DECREASE") {
        assert.ok((c.fromW as number) - c.toW >= p.hysteresisW, "a decrease saves at least the hysteresis");
        const prev = run.changes[k - 1] as (typeof run.changes)[number];
        assert.ok(c.t - prev.t >= p.dwellMin, "no decrease inside the dwell: " + (c.t - prev.t) + " < " + p.dwellMin + " (scenario " + id + ")");
      }
      if (k > 0) {
        const prev = run.changes[k - 1] as (typeof run.changes)[number];
        if (prev.kind === "DECREASE" && c.kind === "INCREASE" && c.t - prev.t < p.dwellMin) reversals++;
      }
    }
    assert.ok(ordinary <= p.maxChanges, "within the changes budget: " + ordinary + " <= " + p.maxChanges);
    if (reversals > 0) reversalScenarios++;
    maxReversals = Math.max(maxReversals, reversals);
    if (sc.calm) {
      calm++;
      if (reversals > 0) calmReversal++;
    }

    // reaching the target
    const reached = run.reachedTolMin !== null && run.reachedTolMin <= run.deadlineMin;
    if (sc.kind === "in-band" && f === "margin") {
      marginAll++;
      if (run.reachedTolMin !== null && run.reachedTolMin <= sc.windowRealMin) marginByEnd++;
      if (sc.paramVariant === "default") {
        marginDefault++;
        if (reached) marginReached++;
        else worstLate = Math.max(worstLate, (run.reachedTolMin ?? Infinity) - run.deadlineMin);
        if (run.reachedStrictMin === null || run.reachedStrictMin > run.deadlineMin) strictMiss++;
      } else {
        marginVaried++;
        if (reached) marginVariedReached++;
      }
      // the dynamic controller against the static planner on the same true battery (default parameters only)
      if (sc.paramVariant === "default") {
        const st = runStatic(sc);
        peakDyn.push(run.peakW);
        peakSta.push(st.rateW);
        peakRatio.push(run.peakW / sc.ceilW);
        if (reached) dynReachCount++;
        if (st.reachedTolMin !== null && st.reachedTolMin <= run.deadlineMin) staReachCount++;
        if (run.reachedTolMin !== null && st.reachedTolMin !== null) {
          both++;
          if (run.reachedTolMin <= st.reachedTolMin) dynNoLater++;
          dyn.push(run.deadlineMin - run.reachedTolMin);
          sta.push(run.deadlineMin - st.reachedTolMin);
        }
      }
    }
    // what the true battery cannot do is reported, not hidden: the controller must have said AT_RISK or UNREACHABLE
    if (f === "infeasible" || f === "buffer") {
      cannot++;
      const flagged = run.ticks.some((tk) => tk.decision.status === "TARGET_AT_RISK" || tk.decision.status === "TARGET_UNREACHABLE");
      if (!flagged) notFlagged++;
      else {
        // and while flagged and not held by the budget, the recommendation is the ceiling (the target is not lowered)
        const tk = run.ticks.find((x) => x.decision.status === "TARGET_AT_RISK" || x.decision.status === "TARGET_UNREACHABLE") as (typeof run.ticks)[number];
        if (tk.decision.neededW === null) assert.ok(tk.decision.setpointW === tk.decision.ceilingW || tk.decision.codes.includes("HELD_BUDGET") || tk.decision.setpointW === tk.appliedBefore);
      }
    }
    void tol;
  }

  const mean = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
  const sd = (a: number[]) => Math.sqrt(mean(a.map((x) => (x - mean(a)) ** 2)));
  const pct = (a: number, b: number) => (b === 0 ? "n/a" : ((100 * a) / b).toFixed(0) + " %");
  console.log("[gentle closed loop] " + N + " seeded scenarios, " + rules + " controller ticks; targets " + [...targets].sort().join("/") + "; " + buffers.size + " distinct buffers 0-120");
  console.log("[gentle closed loop] true-battery feasibility at the full ceiling: " + JSON.stringify(cats));
  console.log("[gentle closed loop] reached = true SOC within half the reading step plus the noise amplitude of the target (the controller stops at the REPORTED target); strict (true SOC >= target) missed in " + strictMiss + " of " + marginDefault + " default-parameter feasible runs");
  console.log("[gentle closed loop] feasible with margin, default parameters: " + marginReached + " of " + marginDefault + " reached by the deadline (" + pct(marginReached, marginDefault) + "); worst lateness " + (worstLate === -Infinity ? "none" : worstLate + " min"));
  console.log("[gentle closed loop] feasible with margin, varied dwell / hysteresis / budget: " + marginVariedReached + " of " + marginVaried + " reached by the deadline; all feasible-with-margin runs reached by the window end: " + marginByEnd + " of " + marginAll);
  console.log("[gentle closed loop] the true battery cannot make the deadline in " + cannot + " scenarios; the controller flagged AT_RISK or UNREACHABLE in all but " + notFlagged);
  console.log("[gentle closed loop] direction reversals (decrease then increase inside the dwell): " + reversalScenarios + " of " + N + " scenarios (max " + maxReversals + " in one), " + calmReversal + " of " + calm + " calm ones; increases checked against the never-held-back rule: " + incChecked);
  console.log("[gentle vs static] feasible-with-margin default runs: dynamic reached the deadline " + dynReachCount + " of " + marginDefault + ", static fixed rate " + staReachCount + " of " + marginDefault);
  console.log("[gentle vs static] dynamic finished no later than static in " + dynNoLater + " of " + both + " (" + pct(dynNoLater, both) + ")");
  console.log("[gentle vs static] peak setpoint: dynamic mean " + mean(peakDyn).toFixed(0) + " W, static mean " + mean(peakSta).toFixed(0) + " W; dynamic peak / ceiling mean " + mean(peakRatio).toFixed(2));
  console.log("[gentle vs static] minutes finished before the deadline: dynamic mean " + mean(dyn).toFixed(1) + " (sd " + sd(dyn).toFixed(1) + "), static mean " + mean(sta).toFixed(1) + " (sd " + sd(sta).toFixed(1) + ")");

  assert.ok(N >= 300 && targets.has(80) && targets.has(90) && targets.has(100));
  assert.ok(buffers.size >= 20 && Math.min(...buffers) === 0 && Math.max(...buffers) <= 120);
  assert.ok(marginDefault >= 150, "enough feasible default scenarios: " + marginDefault);
  assert.ok(cannot >= 20, "scenarios the true battery cannot make are present and reported: " + cannot);
  // THE claim, with its tolerance stated: every feasible-with-margin default run reaches the target (within the reading tolerance) by the deadline.
  assert.equal(marginReached, marginDefault, "feasible-with-margin default runs that missed the deadline: " + (marginDefault - marginReached) + ", worst " + worstLate + " min late");
  assert.equal(marginByEnd, marginAll, "every feasible-with-margin run, whatever the dwell / hysteresis / budget, reaches the target by the window end");
  assert.equal(notFlagged, 0, "every scenario the true battery cannot make was flagged AT_RISK or UNREACHABLE by the controller");
  assert.ok(reversalScenarios <= N * 0.05, "decrease-then-increase reversals are rare: " + reversalScenarios);
  assert.ok(calmReversal <= calm * 0.05, "and rarer still in calm scenarios: " + calmReversal + " of " + calm);
  assert.ok(maxReversals <= 2, "never a run of reversals: " + maxReversals);
  assert.ok(incChecked > 100, "the never-held-back rule was exercised: " + incChecked);
  assert.ok(dynReachCount >= staReachCount, "the dynamic controller reaches the deadline at least as often as the static fixed rate");
  assert.ok(mean(peakRatio) < 0.9, "gentle: the mean peak setpoint stays below the ceiling");
  // Observations only (not asserted): the share of runs where dynamic finished no later than static, the peak-power and spread figures above.
});

test("model-exact run: with the true battery equal to the model the controller aims at the deadline instead of charging flat out", () => {
  let n = 0;
  let floor = 0;
  for (let id = 0; id < 400 && n < 12; id++) {
    const sc0 = makeScenario(id);
    if (feasibility(sc0) !== "margin" || sc0.targetSocPct > 90 || sc0.calm === false) continue;
    const sc = { ...sc0, trueCapacityKwh: sc0.nominalKwh * 1.06, trueEff: 0.95, trueTaper: { startSocPct: 90, endFraction: 0.15 }, readStep: 0.1, readNoise: 0, staleProb: 0, dips: [], params: {}, paramVariant: "default" as const };
    const run = runClosedLoop(sc);
    assert.ok(run.reachedTolMin !== null && run.reachedTolMin <= run.deadlineMin, "reached by the deadline");
    assert.ok(run.peakW <= sc.ceilW);
    if (run.peakW < 1500) { floor++; continue; }   // a tiny job rides on the 500 W floor and finishes early by construction
    assert.ok(run.deadlineMin - (run.reachedTolMin as number) <= 45, "and not far ahead of it: " + (run.deadlineMin - (run.reachedTolMin as number)) + " min early (scenario " + id + ")");
    n++;
  }
  assert.ok(n >= 8, "scenarios checked: " + n + " (" + floor + " on the minimum-power floor)");
});

test("closed loop: a battery already at or above the target is left alone for the whole window", () => {
  let n = 0;
  for (let id = 0; id < 60; id++) {
    const sc0 = makeScenario(id);
    if (sc0.targetSocPct >= 100) continue;
    const sc = { ...sc0, startSocPct: sc0.targetSocPct + 1.5, readNoise: 0, readStep: 1, staleProb: 0, dips: [] };
    const run = runClosedLoop(sc);
    assert.equal(run.firstStatus, "NOTHING_TO_CHARGE");
    assert.equal(run.changes.length, 0, "no setpoint is ever recommended");
    assert.equal(run.peakW, 0);
    assert.ok(run.ticks.every((tk) => tk.decision.setpointW === null));
    n++;
  }
  assert.ok(n >= 40, "scenarios checked: " + n);
});
