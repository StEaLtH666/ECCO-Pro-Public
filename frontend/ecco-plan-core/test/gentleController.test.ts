import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  planGentle, projectCharge, windowRealMinutes, smallestKnownCeiling, acceptanceFraction, powerFromCurrent,
  CONTROLLER_LABEL, ASSUMED_LABEL, ACTUATION_REASON, DEFAULT_GENTLE_PARAMS,
  gridImportW, batteryHeadroomW, stepProfileAt, stepProfileProblem, NO_GUARANTEE_NOTE, PARAM_PROVENANCE, DEFAULT_GENTLE_POLICY, GENTLE_DEFAULT_BUFFER_MIN, GENTLE_RECOMMENDED_PARAMS,
} from "../src/gentleController.ts";
import type { GentleInput, GentleDecision, GentleParams, GentlePolicy, NamedCeiling, ChargeModel, HouseholdInput, StepPoint } from "../src/gentleController.ts";
import type { ClockDay } from "../src/time.ts";
import { norm } from "../src/time.ts";
import * as G4 from "../src/gentleController.ts";   // v3: new helpers are reached through the namespace
import * as TIME from "../src/time.ts";
import { rng } from "./fixtures.ts";
import { makeScenario, runClosedLoop, runStatic, feasibility, wallAt, trueFinishMin, readTolerance, makeHouseholdScenario, runHouseholdLoop, runStaticHH, feasibilityHH, v1Fingerprint, pickV1, acceptW, trueFraction } from "./support/batterySim.ts";
import type { TrueTaper } from "./support/batterySim.ts";

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

// =================================================================================================================================
// Household demand, solar and grid headroom, safe fallbacks, slew limit and parameter provenance (owner directive 18 Nov 2026).
// Everything here is simulated, never measured. The model is read-only, never guarantees the target and never actuates.
// =================================================================================================================================

// Computed ONCE from the v1 module (commit a0d34b8) by v1Fingerprint: 400 seeded closed-loop runs and 4000 random inputs, v1 fields only.
const GOLDEN_V1_DIGEST = "0449cbd371baaf7748fad96ef6391ebb9aeaf70436e82a8d69e66c29a15827e0";
const hbase: GentleInput = { ...base, bufferMin: GENTLE_DEFAULT_BUFFER_MIN };
// v3 G4: a forecast counts only with a fresh age. The old checks were written before forecasts had an age, so this helper gives a profile that has no
// age one of 0 minutes (fresh); the checks of the age rule itself call planGentle directly.
const withAges = (h: HouseholdInput | undefined): HouseholdInput | undefined => {
  if (h === undefined || h === null || typeof h !== "object") return h;
  const o: HouseholdInput = { ...h };
  if (o.demandProfile && o.demandProfileAgeMin === undefined) o.demandProfileAgeMin = 0;
  if (o.solarProfile && o.solarProfileAgeMin === undefined) o.solarProfileAgeMin = 0;
  return o;
};
// v3 G5: the default setpoint basis is UNSETTLED (the caps hold under either convention, see the G5 tests). The hand-checked arithmetic of the older
// checks is the grid-side convention, so this helper asks for it explicitly; a check that passes its own policy keeps that and still gets GRID_AC.
const hplan = (h: HouseholdInput | undefined, over: Partial<GentleInput> = {}) => planGentle({ ...hbase, household: withAges(h), ...over, policy: { setpointBasis: "GRID_AC", ...(over.policy ?? {}) } });
const flat = (watts: number): StepPoint[] => [{ fromInMin: 0, watts }];
const PLANNING = new Set(["OK", "DEGRADED", "TARGET_AT_RISK", "TARGET_UNREACHABLE"]);   // v3 G3: DEGRADED (an assumed demand, asked for explicitly) is a planning status
const inf = (x: number | null) => (x === null ? Infinity : x);

test("v1 behaviour is BIT-IDENTICAL without household input: golden master over 400 closed-loop runs and 4000 random inputs; the new behaviours are off by default", () => {
  assert.equal(v1Fingerprint(planGentle), GOLDEN_V1_DIGEST);
  const v1Defaults = { stepW: 100, minW: 500, hardMaxW: 8000, hysteresisW: 500, dwellMin: 30, decreaseSlackMin: 15, replanMin: 10, maxChanges: 6, maxSocAgeMin: 15, socResolutionPct: 1, chargeEff: 0.95, taperStartSocPct: 90, taperEndFraction: 0.15, topHoldMin: 20 };
  for (const [k, v] of Object.entries(v1Defaults)) assert.equal((DEFAULT_GENTLE_PARAMS as unknown as Record<string, number>)[k], v, "v1 default " + k);
  assert.equal(DEFAULT_GENTLE_PARAMS.maxDecreaseStepW, DEFAULT_GENTLE_PARAMS.hardMaxW, "the slew is off by default (never binds)");
  assert.equal(GENTLE_RECOMMENDED_PARAMS.maxDecreaseStepW, 1000);
  assert.deepEqual({ ...DEFAULT_GENTLE_POLICY }, { fallbackPolicy: "KEEP_CURRENT", unknownDemandPolicy: "FALLBACK", setpointBasis: "UNSETTLED" });   // v3 G3: was ASSUME_PROVISIONAL, a guessed constant under a known limit; v3 G5: the explicit basis
  // the golden digest is sensitive: one changed v1 field changes it
  const bent = (i: GentleInput) => ({ ...planGentle(i), neededW: (planGentle(i).neededW ?? 0) + 1 });
  assert.notEqual(v1Fingerprint(bent), GOLDEN_V1_DIGEST);
  // an empty household group changes no v1 number: it only says that no grid limit is known
  const a = plan();
  const b = hplan({}, { bufferMin: 60 });
  for (const k of ["status", "setpointW", "neededW", "finishInMin", "marginMin", "change", "ceilingW", "deadlineInMin"] as const) assert.deepEqual(b[k], a[k], k);
  assert.ok(b.codes.includes("NO_GRID_LIMIT"));
  assert.equal(a.household, null, "no household input, no household report");
  assert.equal(a.headroomCapW, null);
});

test("household formulae (hand-checked): grid import, battery-side headroom never below zero, the efficiency the right way round", () => {
  // 4100 W drawn from the grid is 3895 W at the battery at 0.95; import = 3895 / 0.95 + 1200 - 300 = 5000
  assert.ok(Math.abs(gridImportW(3895, 0.95, 1200, 300) - 5000) < 1e-9);
  // battery-side headroom = 0.95 x (7000 - 1200 + 300) = 5795; charging at it makes the import EXACTLY the limit
  assert.ok(Math.abs(batteryHeadroomW(7000, 1200, 300, 0.95) - 5795) < 1e-9);
  assert.ok(Math.abs(gridImportW(batteryHeadroomW(7000, 1200, 300, 0.95), 0.95, 1200, 300) - 7000) < 1e-9);
  assert.equal(batteryHeadroomW(1000, 1500, 0, 0.95), 0, "never below zero");
  assert.equal(batteryHeadroomW(0, 0, 0, 0.95), 0);
  assert.ok(batteryHeadroomW(7000, 1200, 300, 0.95) < batteryHeadroomW(7000, 1200, 300, 1), "a lossier charger leaves less battery-side power");
  const rand = rng(1818);
  for (let n = 0; n < 500; n++) {
    const lim = Math.round(rand() * 12000);
    const dem = Math.round(rand() * 6000);
    const sol = Math.round(rand() * 4000);
    const eff = 0.8 + rand() * 0.2;
    const hr = batteryHeadroomW(lim, dem, sol, eff);
    assert.ok(hr >= 0);
    if (hr > 0) assert.ok(Math.abs(gridImportW(hr, eff, dem, sol) - lim) < 1e-6, "import at the headroom is the limit");
    assert.ok(batteryHeadroomW(lim, dem + 100, sol, eff) <= hr, "more demand never raises it");
    assert.ok(batteryHeadroomW(lim, dem, sol + 100, eff) >= hr, "more solar never lowers it");
    assert.ok(batteryHeadroomW(lim + 100, dem, sol, eff) >= hr, "a higher limit never lowers it");
    assert.ok(gridImportW(1000, eff, dem + 100, sol) > gridImportW(1000, eff, dem, sol), "import grows with demand");
  }
});

test("step profiles: the value in force, the last point holds, nothing before the first point; bad profiles are named", () => {
  const pr: StepPoint[] = [{ fromInMin: 10, watts: 500 }, { fromInMin: 60, watts: 2000 }, { fromInMin: 120, watts: 800 }];
  assert.equal(stepProfileAt(pr, 0), null);
  assert.equal(stepProfileAt(pr, 9.9), null);
  assert.equal(stepProfileAt(pr, 10), 500);
  assert.equal(stepProfileAt(pr, 59), 500);
  assert.equal(stepProfileAt(pr, 60), 2000);
  assert.equal(stepProfileAt(pr, 5000), 800);
  assert.equal(stepProfileProblem(pr), null);
  assert.equal(stepProfileProblem([]), null);
  for (const bad of [null, "x", [{ fromInMin: 0, watts: -1 }], [{ fromInMin: -1, watts: 5 }], [{ fromInMin: NaN, watts: 5 }], [{ fromInMin: 5, watts: 5 }, { fromInMin: 5, watts: 6 }], [{ fromInMin: 9, watts: 5 }, { fromInMin: 3, watts: 6 }], [null], [{ fromInMin: 1 }]]) {
    assert.notEqual(stepProfileProblem(bad), null, JSON.stringify(bad));
  }
});

const CREDIT: Partial<GentleInput> = { params: { solarCreditPct: 100 } };

test("the grid cap (hand-checked): the PEAK of demand and forecast with the margin, never the mean or the minimum; solar only fresh, bounded and confidence-scaled", () => {
  // peak of {now 600, 500, 2000, 800} = 2000; x1.2 margin = 2400; cap = 6000 - 2400 = 3600 W
  const profile: StepPoint[] = [{ fromInMin: 0, watts: 500 }, { fromInMin: 60, watts: 2000 }, { fromInMin: 120, watts: 800 }];
  const peak = hplan({ gridImportLimitW: 6000, demandNowW: 600, demandAgeMin: 0, demandProfile: profile });
  assert.equal(peak.headroomCapW, 3600);
  assert.equal(peak.household?.demandPeakW, 2400);
  assert.equal(peak.household?.demandBasis, "FORECAST");
  assert.equal(peak.limitedBy, "GRID_HEADROOM");
  assert.equal(peak.setpointW, 3600, "the highest safe rate: the target needs more than the cap leaves");
  assert.equal(peak.status, "TARGET_AT_RISK");
  // a fresh reading above the forecast raises the peak; a stale one does not
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 3000, demandAgeMin: 0, demandProfile: profile }).headroomCapW, 2400);
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 3000, demandAgeMin: 16, demandProfile: profile }).headroomCapW, 3600, "stale (over 15 min) is not used");
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 3000, demandAgeMin: 15, demandProfile: profile }).headroomCapW, 2400, "exactly the limit is still fresh");
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 3000, demandAgeMin: null, demandProfile: profile }).headroomCapW, 3600, "no age counts as stale");
  // only the remaining window counts: a point after the window end is outside the horizon
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 600, demandAgeMin: 0, demandProfile: [...profile, { fromInMin: 400, watts: 9000 }] }).headroomCapW, 3600);
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 600, demandAgeMin: 0, demandProfile: [...profile, { fromInMin: 359, watts: 9000 }] }).headroomCapW, 0, "the last window minute counts: 6000 - 10800 is below zero, the cap is zero");
  // the margin is configurable
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 600, demandAgeMin: 0, demandProfile: profile }, { params: { demandMarginPct: 0 } }).headroomCapW, 4000);
  assert.equal(hplan({ gridImportLimitW: 6000, demandNowW: 600, demandAgeMin: 0, demandProfile: profile }, { params: { demandMarginPct: 50 } }).headroomCapW, 3000);
  // v3 G2: solar inside the hard limit is an explicit option now (solarCreditPct, 0 by default); these hand-checks keep their arithmetic by asking for 100 %.
  // solar: min(fresh reading, forecast x confidence); 2000 reading, 4000 forecast: confidence 0.4 counts 1600, 0.5 counts 2000, 1 counts only the reading 2000
  const sol = (conf: number | null, extra: Partial<HouseholdInput> = {}): HouseholdInput => ({ gridImportLimitW: 4500, demandProfile: flat(1000), solarNowW: 2000, solarAgeMin: 1, solarProfile: flat(4000), solarConfidence: conf, ...extra });
  assert.equal(hplan({ ...sol(0.4) }, CREDIT).headroomCapW, 4900);
  assert.equal(hplan({ ...sol(0.4) }, CREDIT).household?.solarCountedMinW, 1600);
  assert.equal(hplan({ ...sol(0.5) }, CREDIT).headroomCapW, 5300);
  assert.equal(hplan({ ...sol(1) }, CREDIT).headroomCapW, 5300, "bounded by the fresh reading");
  assert.equal(hplan({ ...sol(null) }, CREDIT).headroomCapW, 3300, "no confidence: solar not counted");
  assert.equal(hplan({ ...sol(0) }, CREDIT).headroomCapW, 3300);
  assert.equal(hplan({ ...sol(0.5, { solarNowW: null }) }, CREDIT).headroomCapW, 3300, "unknown solar counts as 0");
  assert.equal(hplan({ ...sol(0.5, { solarProfile: null }) }, CREDIT).headroomCapW, 3300, "no forecast bound: not counted");
  assert.equal(hplan({ ...sol(0.5, { solarAgeMin: 16 }) }, CREDIT).headroomCapW, 3300, "stale solar counts as 0");
  assert.ok(hplan({ ...sol(0.5, { solarAgeMin: 16 }) }, CREDIT).codes.includes("SOLAR_IGNORED"));
  assert.equal(hplan({ ...sol(1.5) }, CREDIT).headroomCapW, 3300, "an impossible confidence is ignored, solar is not counted");
  assert.equal(hplan({ ...sol(0.5, { solarNowW: -50 }) }, CREDIT).headroomCapW, 3300);
  // the least solar over the window counts: a forecast that drops to 1000 W later
  assert.equal(hplan({ ...sol(0.5, { solarProfile: [{ fromInMin: 0, watts: 4000 }, { fromInMin: 120, watts: 1000 }] }) }, CREDIT).headroomCapW, 3800, "min over the horizon: 500 W counted -> 4500 - 1200 + 500");
  assert.equal(hplan({ ...sol(0.5, { solarProfile: [{ fromInMin: 30, watts: 4000 }] }) }, CREDIT).headroomCapW, 3300, "no forecast for the first minutes: nothing counted there");
  // a solar surplus never lifts the cap above what the limit allows; the cap never goes below zero
  assert.equal(hplan({ gridImportLimitW: 100, demandProfile: flat(5000) }).headroomCapW, 0);
  assert.equal(hplan({ gridImportLimitW: 100, demandProfile: flat(5000) }).status, "NO_SAFE_CEILING");
  assert.ok(hplan({ gridImportLimitW: 100, demandProfile: flat(5000) }).codes.includes("HEADROOM_BELOW_MIN"));
});

test("grid headroom binds the setpoint, never the ceiling's job: not binding leaves v1 untouched, binding caps and says so; the cap is at least the setpoint, the import at most the limit", () => {
  const free = hplan({ gridImportLimitW: 7000, demandProfile: flat(1000) });
  const v1 = plan({ bufferMin: 60 });
  for (const k of ["status", "setpointW", "neededW", "finishInMin", "marginMin", "change", "codes"] as const) assert.deepEqual(free[k], v1[k], k);
  assert.equal(free.headroomCapW, 5800);
  assert.equal(free.limitedBy, "CEILING");
  assert.equal(free.household?.projectedImportW, 5300, "4100 + 1200 - 0");
  assert.ok(!free.codes.includes("HEADROOM_LIMITED"));
  const tight = hplan({ gridImportLimitW: 5000, demandProfile: flat(1000) });
  assert.equal(tight.headroomCapW, 3800);
  assert.equal(tight.setpointW, 3800);
  assert.equal(tight.limitedBy, "GRID_HEADROOM");
  assert.ok(tight.codes.includes("HEADROOM_LIMITED"));
  assert.equal(tight.household?.projectedImportW, 5000, "at the cap the pessimistic import is exactly the limit");
  assert.equal(tight.ceilingW, 5000, "the ceiling is reported on its own");
  // the window's later minutes: the peak over a SHORTER remaining horizon is lower, so the cap rises as the peak passes
  const later = hplan({ gridImportLimitW: 5000, demandProfile: [{ fromInMin: 0, watts: 1000 }, { fromInMin: 30, watts: 200 }] }, { elapsedMin: 0 });
  assert.equal(later.headroomCapW, 3800, "the peak of the whole horizon, even though it is only the first 30 minutes");
  const peakPast = hplan({ gridImportLimitW: 5000, demandProfile: flat(200) }, { elapsedMin: 100, socPct: 40 });
  assert.equal(peakPast.headroomCapW, 4700);
  // monotone in every household input
  assert.ok((hplan({ gridImportLimitW: 5000, demandProfile: flat(1500) }).headroomCapW as number) < (hplan({ gridImportLimitW: 5000, demandProfile: flat(1000) }).headroomCapW as number), "more demand: a lower cap");
  assert.ok((hplan({ gridImportLimitW: 5200, demandProfile: flat(1000) }).headroomCapW as number) > (hplan({ gridImportLimitW: 5000, demandProfile: flat(1000) }).headroomCapW as number), "a higher limit: a higher cap");
});

test("unknown demand with a KNOWN grid limit follows the chosen policy and says so; an unknown grid limit means no headroom constraint, and says so", () => {
  // v3 G3: ASSUME_PROVISIONAL is no longer the default; these checks ask for it explicitly. The labelled provisional 2000 W (x1.2 margin = 2400) is the floor of the peak
  const ha = (h: HouseholdInput, over: Partial<GentleInput> = {}) => hplan(h, { policy: { unknownDemandPolicy: "ASSUME_PROVISIONAL" }, ...over });
  const assumed = ha({ gridImportLimitW: 6000 });
  assert.equal(assumed.household?.demandBasis, "ASSUMED");
  assert.equal(assumed.household?.demandPeakW, 2400);
  assert.equal(assumed.headroomCapW, 3600);
  assert.ok(assumed.codes.includes("ASSUMED_DEMAND"));
  assert.match(assumed.reasons.join(" "), /assumed, not measured/);
  assert.ok(assumed.provisionalInUse.some((x) => x.name === "assumedDemandW" && x.value === 2000 && x.kind === "MEASURED_REQUIRED" && x.source === "DEFAULT"));
  // a reading alone (no forecast) does not cover the window either: the assumption is a FLOOR, a larger reading wins
  assert.equal(ha({ gridImportLimitW: 6000, demandNowW: 500, demandAgeMin: 0 }).headroomCapW, 3600);
  assert.equal(ha({ gridImportLimitW: 6000, demandNowW: 3000, demandAgeMin: 0 }).headroomCapW, 2400);
  // a forecast that starts later and no fresh reading leaves the first minutes uncovered
  assert.ok(ha({ gridImportLimitW: 6000, demandProfile: [{ fromInMin: 20, watts: 400 }] }).codes.includes("ASSUMED_DEMAND"));
  assert.ok(!ha({ gridImportLimitW: 6000, demandProfile: [{ fromInMin: 0, watts: 400 }] }).codes.includes("ASSUMED_DEMAND"), "a forecast from now covers the window");
  assert.ok(!ha({ gridImportLimitW: 6000, demandNowW: 100, demandAgeMin: 0, demandProfile: [{ fromInMin: 20, watts: 400 }] }).codes.includes("ASSUMED_DEMAND"), "a fresh reading plus a forecast covers it");
  // the assumed value is a parameter
  assert.equal(ha({ gridImportLimitW: 6000 }, { params: { assumedDemandW: 1000 } }).headroomCapW, 4800);
  // policy FALLBACK: no guess; NO_DATA with its own code and a fallback record; nothing is recommended
  const fb = hplan({ gridImportLimitW: 6000 }, { policy: { unknownDemandPolicy: "FALLBACK" }, currentSetpointW: 3000, lastChangeElapsedMin: 0, elapsedMin: 5 });
  assert.equal(fb.status, "NO_DATA");
  assert.ok(fb.codes.includes("HOUSEHOLD_UNUSABLE"));
  assert.equal(fb.setpointW, null);
  assert.equal(fb.changeRecommended, false);
  assert.equal(fb.fallback.applied, true);
  assert.equal(fb.fallback.setpointW, null, "the grid headroom cannot be checked, so even KEEP_CURRENT recommends nothing");
  assert.match(fb.fallback.reason, /cannot be checked/);
  assert.ok(hplan({ gridImportLimitW: 6000, demandProfile: flat(500) }, { policy: { unknownDemandPolicy: "FALLBACK" } }).status !== "NO_DATA", "a forecast from now is enough");
  // an unknown grid limit: no constraint, v1 numbers, the reason says so (the limit is never guessed)
  for (const h of [{ gridImportLimitW: null, demandNowW: 9999, demandAgeMin: 0 }, { demandProfile: flat(9999) }, {}] as HouseholdInput[]) {
    const d = hplan(h);
    const v = plan({ bufferMin: 60 });
    assert.equal(d.setpointW, v.setpointW);
    assert.equal(d.headroomCapW, null);
    assert.equal(d.limitedBy, "CEILING");
    assert.ok(d.codes.includes("NO_GRID_LIMIT"));
    assert.match(d.reasons.join(" "), /No safe grid import limit is known/);
    assert.match(d.reasons.join(" "), /nothing is guessed/);
    assert.equal(d.household?.gridLimitW, null);
    assert.equal(d.household?.demandBasis, "NONE");
    assert.ok(!d.codes.includes("ASSUMED_DEMAND"), "demand does not matter without a limit");
    assert.equal(d.fallback.applied, false);
  }
  assert.equal(hplan({ demandProfile: flat(9999) }, { policy: { unknownDemandPolicy: "FALLBACK" } }).status, "OK", "without a limit even the FALLBACK policy has nothing to fall back from");
});

test("household inputs that cannot be trusted: a known limit with an invalid demand is NO_DATA (never guessed); invalid solar is only ignored; invalid policies are INVALID", () => {
  for (const bad of [
    { gridImportLimitW: NaN }, { gridImportLimitW: -5 }, { gridImportLimitW: "7000" as unknown as number },
    { gridImportLimitW: 6000, demandNowW: -1, demandAgeMin: 0 }, { gridImportLimitW: 6000, demandNowW: NaN, demandAgeMin: 0 },
    { gridImportLimitW: 6000, demandProfile: [{ fromInMin: 10, watts: 5 }, { fromInMin: 5, watts: 5 }] }, { gridImportLimitW: 6000, demandProfile: [{ fromInMin: 0, watts: -5 }] },
    { gridImportLimitW: 6000, demandProfile: "x" as unknown as StepPoint[] },
  ] as HouseholdInput[]) {
    const d = hplan(bad, { currentSetpointW: 3000 });
    assert.equal(d.status, "NO_DATA", JSON.stringify(bad));
    assert.equal(d.setpointW, null);
    assert.ok(d.codes.includes("HOUSEHOLD_INVALID"));
    assert.equal(d.fallback.applied, true);
    assert.equal(d.fallback.setpointW, null, "an invalid household input cannot be checked: no recommendation");
  }
  // a household input that is not even an object fails closed; so does a profile too long to be a profile
  const junk = hplan("x" as unknown as HouseholdInput, { currentSetpointW: 3000 });
  assert.equal(junk.status, "NO_DATA");
  assert.ok(junk.codes.includes("HOUSEHOLD_INVALID"));
  assert.equal(junk.fallback.setpointW, null);
  const many: StepPoint[] = Array.from({ length: 1001 }, (_, k) => ({ fromInMin: k, watts: 100 }));
  assert.equal(hplan({ gridImportLimitW: 6000, demandProfile: many }).status, "NO_DATA");
  assert.match(stepProfileProblem(many) as string, /more than 1000 points/);
  assert.equal(stepProfileProblem(many.slice(0, 1000)), null);
  // without a known limit the same bad demand is irrelevant
  assert.equal(hplan({ demandNowW: -1, demandAgeMin: 0 }).status, "OK");
  // a bad solar input costs only the solar
  const s = hplan({ gridImportLimitW: 4500, demandProfile: flat(1000), solarNowW: 2000, solarAgeMin: 0, solarProfile: [{ fromInMin: 5, watts: 1 }, { fromInMin: 1, watts: 1 }], solarConfidence: 0.5 });
  assert.equal(s.headroomCapW, 3300);
  assert.ok(s.codes.includes("SOLAR_IGNORED"));
  for (const policy of [{ fallbackPolicy: "SOMETIMES" }, { unknownDemandPolicy: "GUESS" }] as unknown as Partial<GentlePolicy>[]) assert.equal(hplan({ gridImportLimitW: 6000 }, { policy }).status, "INVALID");
  for (const params of [{ demandMarginPct: -1 }, { demandMarginPct: 300 }, { assumedDemandW: -1 }, { maxHouseholdAgeMin: 0 }, { maxDecreaseStepW: 50 }, { maxDecreaseStepW: NaN }]) assert.equal(plan({ params }).status, "INVALID", JSON.stringify(params));
  assert.equal(plan({ params: { maxDecreaseStepW: 100, hysteresisW: 100 } }).status, "OK", "one step is the least slew (v3 G7: with a hysteresis that one step can save)");
});

test("TARGET_AT_RISK and TARGET_UNREACHABLE under a grid cap: the highest SAFE rate, the late finish projected, the smallest absorbing buffer, never a lower target, 'NOT guaranteed'", () => {
  const risk = hplan({ gridImportLimitW: 5000, demandProfile: flat(1000) });
  assert.equal(risk.status, "TARGET_AT_RISK");
  assert.equal(risk.setpointW, 3800, "the highest safe rate");
  assert.equal(risk.neededW, null);
  assert.equal(risk.targetSocPct, 80);
  assert.ok(risk.finishInMin !== null && (risk.marginMin as number) < 0, "the late finish is projected");
  assert.ok(risk.suggestedBufferMin !== null && risk.suggestedBufferMin < 60);
  assert.equal(hplan({ gridImportLimitW: 5000, demandProfile: flat(1000) }, { bufferMin: risk.suggestedBufferMin as number }).status, "OK", "the suggested buffer absorbs the delay at the safe rate");
  assert.match(risk.reasons.join(" "), /Buffer too small/);
  assert.match(risk.reasons.join(" "), /safe grid headroom of 3800 W/);
  assert.match(risk.reasons.join(" "), /not lowered/);
  assert.match(risk.reasons.join(" "), /NOT guaranteed/);
  assert.equal(risk.guarantee, "NONE");
  assert.equal(risk.guaranteeNote, NO_GUARANTEE_NOTE);
  const un = hplan({ gridImportLimitW: 5000, demandProfile: flat(2000) }, { targetSocPct: 100, bufferMin: 0, chargeWindow: { startMin: 22 * 60, endMin: 1 * 60, clockDay: ORDINARY } });
  assert.equal(un.status, "TARGET_UNREACHABLE");
  assert.equal(un.finishInMin, null);
  assert.equal(un.setpointW, un.headroomCapW);
  assert.ok((un.setpointW as number) <= (un.ceilingW as number));
  assert.match(un.reasons.join(" "), /even at the safe grid headroom/);
  assert.match(un.reasons.join(" "), /NOT guaranteed/);
  // the limit may be the ceiling: then the v1 wording
  const ceilRisk = hplan({ gridImportLimitW: 20000, demandProfile: flat(1000) }, { targetSocPct: 100, socPct: 40 });
  assert.equal(ceilRisk.status, "TARGET_AT_RISK");
  assert.equal(ceilRisk.limitedBy, "CEILING");
  assert.match(ceilRisk.reasons.join(" "), /safe ceiling of 5000 W/);
  // in every status the note says what it must say, in plain words
  assert.match(NO_GUARANTEE_NOTE, /NOT guaranteed/);
  assert.match(NO_GUARANTEE_NOTE, /100 percent/);
  assert.match(NO_GUARANTEE_NOTE, /fixed rate/);
  assert.match(NO_GUARANTEE_NOTE, /taper/);
  assert.match(NO_GUARANTEE_NOTE, /read-only/);
  for (const d of [risk, un, ceilRisk, plan(), plan({ socPct: null }), plan({ targetSocPct: 9 }), plan({ socPct: 90 }), plan({ ceilings: [] })]) {
    assert.equal(d.guarantee, "NONE");
    assert.equal(d.guaranteeNote, NO_GUARANTEE_NOTE);
    assert.equal(d.actuationSupported, false);
  }
});

test("fallbacks: KEEP_CURRENT, USE_STATIC_PLAN and NONE apply when the SOC is unknown or stale, the ceiling is unknown or the household input unusable; never above a limit; never a normal OK", () => {
  const stale: Partial<GentleInput> = { socAgeMin: 99, currentSetpointW: 3000 };
  // KEEP_CURRENT (the default): hold the setpoint in force while it is within the ceiling
  const keep = plan(stale);
  assert.equal(keep.status, "NO_DATA", "a fallback is never a normal OK");
  assert.equal(keep.setpointW, null, "the normal recommendation stays empty");
  assert.equal(keep.changeRecommended, false);
  assert.deepEqual({ applied: keep.fallback.applied, policy: keep.fallback.policy, setpointW: keep.fallback.setpointW }, { applied: true, policy: "KEEP_CURRENT", setpointW: 3000 });
  assert.match(keep.fallback.reason, /fallback, not a plan/i);
  // ... but NOT above the ceiling: KEEP_CURRENT would exceed a limit
  const over = plan({ socAgeMin: 99, currentSetpointW: 5500 });
  assert.equal(over.fallback.setpointW, null);
  assert.match(over.fallback.reason, /above the safe limit/);
  assert.equal(plan({ socAgeMin: 99, currentSetpointW: 5000 }).fallback.setpointW, 5000, "exactly the ceiling is within it");
  // ... nor above the grid headroom cap
  const cap33: HouseholdInput = { gridImportLimitW: 4500, demandProfile: flat(1000) };
  assert.equal(hplan(cap33, { ...stale, currentSetpointW: 3300 }).fallback.setpointW, 3300);
  assert.equal(hplan(cap33, { ...stale, currentSetpointW: 3400 }).fallback.setpointW, null, "above the cap of 3300 W");
  assert.match(hplan(cap33, { ...stale, currentSetpointW: 3400 }).fallback.reason, /above the safe limit \(3300 W\)/);
  // nothing in force: nothing to keep
  assert.equal(plan({ socAgeMin: 99, currentSetpointW: null }).fallback.setpointW, null);
  assert.equal(plan({ socAgeMin: 99, currentSetpointW: 0 }).fallback.setpointW, null);
  // an unknown ceiling cannot be checked: no recommendation, whatever the policy
  for (const policy of ["KEEP_CURRENT", "USE_STATIC_PLAN"] as const) {
    const d = plan({ ceilings: [], currentSetpointW: 3000, staticPlanRateW: 3000, policy: { fallbackPolicy: policy } });
    assert.equal(d.status, "NO_SAFE_CEILING");
    assert.equal(d.fallback.applied, true);
    assert.equal(d.fallback.setpointW, null);
    assert.match(d.fallback.reason, /ceiling is unknown/);
  }
  // USE_STATIC_PLAN: the static rate, never raised above the ceiling or the cap, rounded down to a step
  const useStatic = (rate: number | null | undefined, over2: Partial<GentleInput> = {}, h?: HouseholdInput) => hplan(h, { socAgeMin: 99, policy: { fallbackPolicy: "USE_STATIC_PLAN" }, staticPlanRateW: rate, ...over2 }).fallback;
  assert.equal(useStatic(4000).setpointW, 4000);
  assert.equal(useStatic(4050).setpointW, 4000);
  assert.equal(useStatic(6000).setpointW, 5000, "lowered to the ceiling");
  assert.match(useStatic(6000).reason, /lowered from 6000 W/);
  assert.equal(useStatic(4000, {}, cap33).setpointW, 3300, "lowered to the grid cap");
  assert.equal(useStatic(4000, { currentSetpointW: 1000 }).setpointW, 4000, "independent of the setpoint in force");
  for (const bad of [null, undefined, 300, NaN, -4000]) assert.equal(useStatic(bad as number | null).setpointW, null, String(bad));
  assert.equal(useStatic(4000, {}, { gridImportLimitW: 100, demandProfile: flat(5000) }).setpointW, null, "no safe setpoint under the cap");
  // NONE
  const none = plan({ socAgeMin: 99, currentSetpointW: 3000, policy: { fallbackPolicy: "NONE" } });
  assert.equal(none.fallback.applied, true);
  assert.equal(none.fallback.setpointW, null);
  assert.equal(none.fallback.policy, "NONE");
  // an ordinary plan has no fallback
  for (const d of [plan(), plan({ socPct: 90 }), hplan({ gridImportLimitW: 5000, demandProfile: flat(1000) })]) {
    assert.equal(d.fallback.applied, false);
    assert.equal(d.fallback.setpointW, null);
  }
  // every cause of a fallback
  const causes: [Partial<GentleInput>, string][] = [[{ socPct: null }, "NO_DATA"], [{ socAgeMin: 99 }, "NO_DATA"], [{ socPct: 150 }, "NO_DATA"], [{ ceilings: [{ name: "a", watts: 300 }] }, "NO_SAFE_CEILING"]];
  for (const [c, st] of causes) {
    const d = plan({ currentSetpointW: 3000, ...c });
    assert.equal(d.status, st);
    assert.equal(d.fallback.applied, true);
    assert.equal(d.setpointW, null);
  }
  // the policy is the owner's: v1 results never depend on it
  assert.deepEqual(pickV1(plan({ policy: { fallbackPolicy: "NONE" } })), pickV1(plan()));
});

test("slew limit: a decrease goes down by at most maxDecreaseStepW per change; a deadline increase may jump, flagged JUMP_FOR_DEADLINE and counted; a safety decrease is never softened", () => {
  const at = (over2: Partial<GentleInput>) => plan({ currentSetpointW: 5000, lastChangeElapsedMin: 0, elapsedMin: 100, socPct: 45, ...over2 });
  const free = at({});
  assert.equal(free.setpointW, 3900, "without a slew the plan goes straight down (v1)");
  const slewed = at({ params: { maxDecreaseStepW: 1000 } });
  assert.equal(slewed.setpointW, 4000);
  assert.ok(slewed.codes.includes("DECREASE_SAVING") && slewed.codes.includes("SLEW_LIMITED"));
  assert.equal(slewed.change, "DECREASE");
  assert.equal(slewed.changesUsed, 1, "a slewed decrease still draws on the budget");
  assert.equal(slewed.neededW, free.neededW, "the need is unchanged: only the pace");
  assert.equal(at({ params: { maxDecreaseStepW: 1100 } }).setpointW, 3900, "a limit that covers the whole step does not bind");
  assert.ok(!at({ params: { maxDecreaseStepW: 1100 } }).codes.includes("SLEW_LIMITED"));
  assert.equal(at({ params: { maxDecreaseStepW: 100, hysteresisW: 0 } }).setpointW, 4900);
  // gradual: stepping down the staircase never exceeds the limit
  let cur = 5000;
  let last = 0;
  for (let k = 0; k < 8; k++) {
    const d = plan({ currentSetpointW: cur, lastChangeElapsedMin: last, elapsedMin: last + 40, socPct: 45, params: { maxDecreaseStepW: 300, hysteresisW: 100, dwellMin: 30 } });
    if (d.change !== "DECREASE") break;
    assert.ok(cur - (d.setpointW as number) <= 300, "step " + k);
    cur = d.setpointW as number;
    last += 40;
  }
  assert.ok(cur <= 4400 && cur >= 3600, "it did come down in steps, and not below what the deadline needs: " + cur);
  // an increase needed for the deadline may exceed the limit: flagged and counted
  const jump = plan({ currentSetpointW: 1500, lastChangeElapsedMin: 50, elapsedMin: 100, socPct: 35, params: { maxDecreaseStepW: 1000 } });
  assert.equal(jump.change, "INCREASE");
  assert.equal(jump.setpointW, jump.neededW);
  assert.ok((jump.setpointW as number) - 1500 > 1000);
  assert.ok(jump.codes.includes("JUMP_FOR_DEADLINE") && jump.codes.includes("INCREASE_FOR_DEADLINE"));
  assert.equal(jump.jumpForDeadline, true);
  assert.equal(jump.changesUsed, 1, "counted against the budget");
  assert.match(jump.reasons.join(" "), /over the 1000 W slew limit/);
  const smallUp = plan({ currentSetpointW: 4500, lastChangeElapsedMin: 50, elapsedMin: 100, socPct: 35, params: { maxDecreaseStepW: 1000 } });
  assert.equal(smallUp.change, "INCREASE");
  assert.equal(smallUp.jumpForDeadline, false);
  assert.ok(!smallUp.codes.includes("JUMP_FOR_DEADLINE"));
  assert.equal(plan({ currentSetpointW: 1500, lastChangeElapsedMin: 50, elapsedMin: 100, socPct: 35 }).jumpForDeadline, false, "off by default");
  // a safety decrease goes to the safe value at once, whatever the slew
  const safety = plan({ currentSetpointW: 4800, lastChangeElapsedMin: 0, elapsedMin: 1, ceilings: [{ name: "battery_max_charge", watts: 3000 }], params: { maxDecreaseStepW: 100, hysteresisW: 100 } });
  assert.ok(safety.codes.includes("ABOVE_CEILING"));
  assert.ok((safety.setpointW as number) <= 3000);
  const hsafe = hplan({ gridImportLimitW: 5000, demandProfile: flat(1000) }, { currentSetpointW: 4800, lastChangeElapsedMin: 0, elapsedMin: 1, changesUsed: 6, params: { maxDecreaseStepW: 100, hysteresisW: 100 } });
  assert.ok(hsafe.codes.includes("ABOVE_HEADROOM"));
  assert.equal(hsafe.setpointW, 3800);
  assert.equal(hsafe.changesUsed, 6, "a safety decrease does not draw on the budget");
  assert.match(hsafe.reasons.join(" "), /safe grid headroom \(3800 W\)/);
});

test("a recovering grid headroom is followed like a saving, not like a deadline need: it waits for the hysteresis and the dwell; a deadline need is never held; a fall is immediate", () => {
  const G = { gridImportLimitW: 4500, demandProfile: flat(1000) };   // cap 3300 W; the target needs a little more, so the plan is at risk and rides the cap
  const at = (cur: number, since: number, over2: Partial<GentleInput> = {}) => hplan(G, { currentSetpointW: cur, lastChangeElapsedMin: 60 - since, elapsedMin: 60, socPct: 40, ...over2 });
  const small = at(3000, 40);
  assert.equal(small.status, "TARGET_AT_RISK");
  assert.equal(small.neededW, null);
  assert.equal(small.change, "NONE", "300 W up is under the 500 W hysteresis");
  assert.ok(small.codes.includes("HELD_HYSTERESIS"));
  assert.equal(small.setpointW, 3000);
  const fresh = at(2500, 5);
  assert.equal(fresh.change, "NONE");
  assert.ok(fresh.codes.includes("HELD_DWELL"));
  assert.match(fresh.reasons.join(" "), /no flapping/);
  const ok = at(2500, 30);
  assert.equal(ok.change, "INCREASE");
  assert.equal(ok.setpointW, 3300);
  assert.equal(at(2500, 29).change, "NONE", "the dwell is exact");
  assert.equal(at(2500, 0, { lastChangeElapsedMin: null }).change, "INCREASE", "no change history: nothing to wait for");
  assert.equal(at(2500, 5, { changesUsed: 6 }).codes.includes("HELD_BUDGET"), true, "an exhausted budget still holds, as in v1");
  // a deadline need that cannot wait is never held back (the plan is feasible inside the cap)
  const need = hplan({ gridImportLimitW: 9000, demandProfile: flat(1000) }, { currentSetpointW: 1500, lastChangeElapsedMin: 55, elapsedMin: 60, socPct: 25 });
  assert.equal(need.change, "INCREASE");
  assert.ok(need.codes.includes("INCREASE_FOR_DEADLINE"));
  assert.equal(need.status, "OK");
  // and a fall of the cap lowers the setpoint at once (checked above for the budget and the slew)
  const fall = at(3300, 1);
  assert.equal(fall.setpointW, 3300);
  assert.equal(at(3900, 1).setpointW, 3300);
  assert.ok(at(3900, 1).codes.includes("ABOVE_HEADROOM"));
});

test("an increase that the deadline can WAIT for waits out the dwell (no flapping on noisy inputs); one that cannot wait is made now; without household input v1 never waits", () => {
  const G: HouseholdInput = { gridImportLimitW: 30000, demandProfile: flat(500) };
  const st = (soc: number, since: number, h: HouseholdInput | undefined = G) => hplan(h, { currentSetpointW: 3000, lastChangeElapsedMin: 60 - since, elapsedMin: 60, socPct: soc });
  // 35 %: the need is about 3900 W; after 25 more minutes at 3000 W a raise to the 5000 W ceiling still makes the deadline with 15 min of slack
  const wait = st(35, 5);
  assert.equal(wait.change, "NONE");
  assert.equal(wait.setpointW, 3000);
  assert.ok(wait.codes.includes("HELD_DWELL"));
  assert.equal(wait.status, "OK", "waiting is part of a plan that still makes the deadline");
  // v3 G7 m5: the projection used to assume a raise to the CEILING after the dwell (a margin of at least the 15 min slack); the later raise goes to the
  // LOWEST step that still makes the deadline, so the margin shown is that one: not negative, and well under the slack a raise to the ceiling would show.
  assert.ok((wait.marginMin as number) >= -0.11 && (wait.marginMin as number) < 15 - 5, "the projection is the later lowest-step raise's: " + wait.marginMin);
  assert.match(wait.reasons.join(" "), /deadline still holds/);
  assert.equal(wait.changesUsed, 0);
  assert.ok((wait.neededW as number) > 3000, "the increase was wanted");
  // the dwell is exact: 30 minutes since the last change, no wait
  assert.equal(st(35, 30).change, "INCREASE");
  assert.equal(st(35, 29).change, "NONE");
  // 25 %: the same wait would cost the deadline, so the raise is made now
  const now = st(25, 5);
  assert.equal(now.change, "INCREASE");
  assert.ok(now.codes.includes("INCREASE_FOR_DEADLINE"));
  // the budget still comes first, and v1 (no household input) never waits
  assert.ok(st(35, 5).changesUsed === 0 && hplan(G, { currentSetpointW: 3000, lastChangeElapsedMin: 55, elapsedMin: 60, socPct: 35, changesUsed: 6 }).codes.includes("HELD_BUDGET"));
  assert.equal(hplan(undefined, { currentSetpointW: 3000, lastChangeElapsedMin: 55, elapsedMin: 60, socPct: 35 }).change, "INCREASE", "v1: an increase needed for the deadline is never held back");
  assert.equal(st(35, 5, { gridImportLimitW: null }).change, "INCREASE", "no grid limit: no household mode, the v1 rule");
  assert.equal(plan({ currentSetpointW: 3000, lastChangeElapsedMin: 55, elapsedMin: 60, socPct: 35, bufferMin: 60 }).change, "INCREASE");
});

test("parameter provenance: every parameter is PROVISIONAL, OWNER_SET or MEASURED_REQUIRED, the decision lists the provisional ones in use, the README has the table", () => {
  const kinds = new Set(["PROVISIONAL", "OWNER_SET", "MEASURED_REQUIRED"]);
  const names = [...Object.keys(DEFAULT_GENTLE_PARAMS), ...Object.keys(DEFAULT_GENTLE_POLICY), "targetSocPct", "bufferMin", "gridImportLimitW"];
  for (const n of names) {
    const pv = PARAM_PROVENANCE[n];
    assert.ok(pv, "provenance for " + n);
    assert.ok(kinds.has((pv as { kind: string }).kind), n);
    assert.ok((pv as { replacedBy: string }).replacedBy.length > 8, n + " says what replaces it");
  }
  assert.equal(Object.keys(PARAM_PROVENANCE).length, names.length, "no stray entries");
  assert.ok(Object.isFrozen(PARAM_PROVENANCE) && Object.isFrozen(PARAM_PROVENANCE.stepW));
  for (const [k, v] of Object.entries(DEFAULT_GENTLE_PARAMS)) assert.equal((PARAM_PROVENANCE[k] as { value: unknown }).value, v, k);
  assert.equal((PARAM_PROVENANCE.bufferMin as { value: unknown }).value, GENTLE_DEFAULT_BUFFER_MIN);
  assert.equal(GENTLE_DEFAULT_BUFFER_MIN, 60);
  assert.equal(GENTLE_DEFAULT_BUFFER_MIN % 5, 0);
  assert.equal(plan({ bufferMin: GENTLE_DEFAULT_BUFFER_MIN }).status, "OK", "the default buffer is on the validation grid");
  const byKind = (k: string) => names.filter((n) => (PARAM_PROVENANCE[n] as { kind: string }).kind === k).sort();
  assert.deepEqual(byKind("OWNER_SET"), ["bufferMin", "gridImportLimitW", "hardMaxW", "minW", "stepW", "targetSocPct"]);
  assert.deepEqual(byKind("MEASURED_REQUIRED"), ["assumedDemandW", "taperEndFraction", "taperStartSocPct", "topHoldMin"]);
  assert.ok(byKind("PROVISIONAL").includes("demandMarginPct") && byKind("PROVISIONAL").includes("maxDecreaseStepW") && byKind("PROVISIONAL").includes("fallbackPolicy"));
  // the decision lists them
  const d = plan();
  const listed = d.provisionalInUse.map((x) => x.name);
  assert.ok(d.provisionalInUse.length >= 9, "provisional parameters are listed: " + listed.join(","));
  for (const x of d.provisionalInUse) {
    assert.notEqual(x.kind, "OWNER_SET");
    assert.equal(x.kind, (PARAM_PROVENANCE[x.name] as { kind: string }).kind);
    assert.equal(x.source, "DEFAULT");
    assert.equal(x.value, (PARAM_PROVENANCE[x.name] as { value: unknown }).value);
  }
  for (const must of ["hysteresisW", "dwellMin", "chargeEff", "taperStartSocPct", "taperEndFraction", "maxSocAgeMin"]) assert.ok(listed.includes(must), must);
  assert.ok(!listed.includes("topHoldMin"), "the hold only applies at 100 %");
  assert.ok(plan({ targetSocPct: 100, socPct: 60, ceilings: [{ name: "o", watts: 8000 }] }).provisionalInUse.some((x) => x.name === "topHoldMin" && x.kind === "MEASURED_REQUIRED"));
  assert.ok(!listed.includes("demandMarginPct") && !listed.includes("maxDecreaseStepW"), "household and slew parameters only when they act");
  assert.ok(!listed.includes("stepW") && !listed.includes("targetSocPct"), "owner-set values are not provisional");
  const withHh = hplan({ gridImportLimitW: 6000, demandProfile: flat(500) }, { params: { maxDecreaseStepW: 1000, dwellMin: 45 } });
  const wl = withHh.provisionalInUse;
  assert.ok(wl.some((x) => x.name === "demandMarginPct" && x.value === 20 && x.source === "DEFAULT"));
  assert.ok(wl.some((x) => x.name === "maxDecreaseStepW" && x.value === 1000 && x.source === "CALLER"));
  assert.ok(wl.some((x) => x.name === "dwellMin" && x.value === 45 && x.source === "CALLER"), "a caller-set value is shown as such");
  assert.ok(!wl.some((x) => x.name === "assumedDemandW"), "the assumption is listed only when it is used");
  const asked = { policy: { unknownDemandPolicy: "ASSUME_PROVISIONAL" } } as Partial<GentleInput>;   // v3 G3: explicit
  assert.ok(hplan({ gridImportLimitW: 6000 }, asked).provisionalInUse.some((x) => x.name === "assumedDemandW"));
  assert.ok(hplan({ gridImportLimitW: 6000 }, asked).provisionalInUse.some((x) => x.name === "unknownDemandPolicy"));
  assert.ok(plan({ socAgeMin: 99 }).provisionalInUse.some((x) => x.name === "fallbackPolicy" && x.value === "KEEP_CURRENT"));
  assert.deepEqual(plan({ targetSocPct: 9 }).provisionalInUse, [], "an invalid input lists nothing");
  // the README has one table: value, kind and what would replace it
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  for (const n of names) {
    const row = readme.split(/\r?\n/).find((l) => l.startsWith("|") && l.includes("`" + n + "`"));
    assert.ok(row, "README table row for " + n);
    const pv = PARAM_PROVENANCE[n] as { kind: string; value: number | string };
    assert.ok((row as string).includes(pv.kind), n + " kind " + pv.kind);
    if (typeof pv.value === "number") assert.ok((row as string).includes(String(pv.value)), n + " value");
  }
  assert.match(readme, /NOT guaranteed|not guaranteed/);
  assert.match(readme, /read-only|read only/);
  assert.match(readme, /nothing actuates|NOTHING actuates|Nothing actuates/i);
});

test("projectCharge with a grid headroom per minute: delivered = min(setpoint, taper acceptance, headroom at that minute); the last value holds; none is the v1 projection", () => {
  const m: ChargeModel = { capacityKwh: 30, chargeEff: 0.95, ceilingW: 8000, taperStartSocPct: 90, taperEndFraction: 0.15 };
  const free = projectCharge(20, 4000, 80, m, 600).finishMin as number;
  assert.equal(projectCharge(20, 4000, 80, { ...m, headroomW: undefined }, 600).finishMin, free);
  assert.equal(projectCharge(20, 4000, 80, { ...m, headroomW: [9000] }, 600).finishMin, free, "a headroom above the setpoint changes nothing");
  // constant 2000 W headroom: 18 kWh / (2 kW x 0.95) = 9.47 h = 568.4 min
  const slow = projectCharge(20, 4000, 80, { ...m, headroomW: [2000] }, 900).finishMin as number;
  assert.ok(Math.abs(slow - (18 / (2 * 0.95)) * 60) < 1.01, "constant headroom: " + slow);
  // 60 minutes at 1000 W then 4000 W: strictly between the two constants
  const arr = new Array(60).fill(1000).concat([4000]);
  const mixed = projectCharge(20, 4000, 80, { ...m, headroomW: arr }, 900).finishMin as number;
  assert.ok(mixed > free && mixed < slow);
  const expected = 60 + (18 - (1 * 0.95)) / (4 * 0.95) * 60;   // 0.95 kWh in the first hour, the rest at 4000 W x 0.95 (below the taper)
  assert.ok(Math.abs(mixed - expected) < 3, "hand-checked: " + mixed + " vs " + expected);
  assert.equal(projectCharge(20, 4000, 80, { ...m, headroomW: [0] }, 900).finishMin, null, "zero headroom: never");
  assert.equal(projectCharge(20, 4000, 80, { ...m, headroomW: [] }, 900).finishMin, null, "an empty headroom is zero, not unlimited");
  assert.equal(projectCharge(80, 4000, 80, { ...m, headroomW: [0] }, 900).finishMin, 0, "already there");
  // the headroom is a limit on the same delivered power the taper limits: the lower of the two applies
  const tapered = projectCharge(85, 8000, 100, { ...m, headroomW: [8000] }, 900).finishMin as number;
  const both = projectCharge(85, 8000, 100, { ...m, headroomW: [900] }, 2000).finishMin as number;
  assert.ok(both > tapered);
});

// ---- random properties over household inputs ------------------------------------------------------------------------------------

function randomHousehold(rand: () => number): HouseholdInput | undefined {
  if (rand() < 0.12) return undefined;
  const profile = (maxW: number): StepPoint[] | null => {
    if (rand() < 0.2) return null;
    const out: StepPoint[] = [];
    let m = rand() < 0.7 ? 0 : 10 + Math.floor(rand() * 60);
    for (let k = 0, n = 1 + Math.floor(rand() * 4); k < n; k++) {
      out.push({ fromInMin: m, watts: Math.round(rand() * maxW) });
      m += 20 + Math.floor(rand() * 100);
    }
    return out;
  };
  return {
    gridImportLimitW: rand() < 0.15 ? null : 1000 + Math.floor(rand() * 11000),
    demandNowW: rand() < 0.2 ? null : Math.round(rand() * 4000), demandAgeMin: rand() < 0.15 ? 60 : Math.floor(rand() * 10), demandProfile: profile(4000), demandProfileAgeMin: rand() < 0.1 ? 600 : Math.floor(rand() * 60),
    solarNowW: rand() < 0.3 ? null : Math.round(rand() * 5000), solarAgeMin: rand() < 0.1 ? 60 : Math.floor(rand() * 10), solarProfile: profile(5000), solarProfileAgeMin: rand() < 0.1 ? 600 : Math.floor(rand() * 60),
    solarConfidence: rand() < 0.15 ? null : Math.round(rand() * 100) / 100,
  };
}

function householdCase(rand: () => number): GentleInput {
  const i = randomInput(rand);
  return { ...i, household: randomHousehold(rand), socPct: 5 + Math.floor(rand() * 85), socAgeMin: rand() < 0.2 ? 60 : 1, policy: rand() < 0.3 ? { fallbackPolicy: (["KEEP_CURRENT", "USE_STATIC_PLAN", "NONE"] as const)[Math.floor(rand() * 3)] as "NONE", unknownDemandPolicy: rand() < 0.5 ? "FALLBACK" : "ASSUME_PROVISIONAL" } : undefined, staticPlanRateW: rand() < 0.6 ? 500 + 100 * Math.floor(rand() * 80) : null };
}

test("property (5000 random household inputs): never above the ceiling or the grid cap, import never above the limit, fallbacks never above a limit, guarantee NONE, no mutation", () => {
  const rand = rng(1811);
  const seen: Record<string, number> = {};
  let capped = 0;
  let withImport = 0;
  let fallbackHeld = 0;
  for (let n = 0; n < 5000; n++) {
    const i = householdCase(rand);
    const before = JSON.stringify(i);
    const d = planGentle(i);
    assert.equal(JSON.stringify(i), before, "the input is not mutated");
    seen[d.status] = (seen[d.status] ?? 0) + 1;
    assert.equal(d.guarantee, "NONE");
    assert.equal(d.guaranteeNote, NO_GUARANTEE_NOTE);
    assert.equal(d.actuationSupported, false);
    assert.equal(d.targetSocPct, i.targetSocPct);
    assert.equal(d.label, CONTROLLER_LABEL);
    for (const x of d.provisionalInUse) assert.ok(x.kind !== "OWNER_SET" && PARAM_PROVENANCE[x.name] !== undefined);
    const p = { ...DEFAULT_GENTLE_PARAMS, ...(i.params ?? {}) };
    const lim = i.household?.gridImportLimitW;
    const limitKnown = typeof lim === "number" && Number.isFinite(lim) && lim >= 0;
    if (d.setpointW !== null) {
      assert.equal(d.setpointW % p.stepW, 0);
      assert.ok(d.setpointW <= (d.ceilingW as number) && d.setpointW <= knownMin(i.ceilings));
      if (d.headroomCapW !== null) {
        capped++;
        assert.ok(d.setpointW <= d.headroomCapW, "never above the grid cap: " + d.setpointW + " vs " + d.headroomCapW);
        assert.ok(limitKnown);
        const imp = (d.household as { projectedImportW: number | null }).projectedImportW;
        assert.ok(imp !== null && imp <= (lim as number) + 1e-6, "the pessimistic import stays inside the limit: " + imp + " vs " + lim);
        withImport++;
      }
      assert.equal(d.fallback.applied, false, "a recommendation is never a fallback");
    }
    if (i.household === undefined && PLANNING.has(d.status)) assert.equal(d.household, null);
    if (PLANNING.has(d.status) && i.household !== undefined && !limitKnown) {
      assert.equal(d.headroomCapW, null, "no limit, no cap");
      assert.ok(d.codes.includes("NO_GRID_LIMIT"));
    }
    if (d.fallback.applied) {
      assert.ok(d.status === "NO_DATA" || d.status === "NO_SAFE_CEILING", "a fallback only where the plan cannot run: " + d.status);
      assert.equal(d.setpointW, null);
      assert.equal(d.changeRecommended, false);
      const fw = d.fallback.setpointW;
      if (fw !== null) {
        fallbackHeld++;
        assert.ok(fw <= knownMin(i.ceilings) && fw <= p.hardMaxW && fw >= p.minW, "the fallback respects the ceiling: " + fw);
        if (d.fallback.policy === "KEEP_CURRENT") assert.equal(fw, i.currentSetpointW);
        if (d.fallback.policy === "USE_STATIC_PLAN") assert.ok(fw <= (i.staticPlanRateW as number) && fw % p.stepW === 0);
        assert.notEqual(d.fallback.policy, "NONE");
        if (limitKnown && i.household && (i.household.demandProfile || i.household.demandNowW !== null) ) {
          // with a limit and some demand the fallback is also inside the cap: probe the same state with a fresh SOC
          const probe = planGentle({ ...i, socPct: 5, socAgeMin: 0, targetSocPct: Math.max(i.targetSocPct, 50) });
          if (probe.headroomCapW !== null) assert.ok(fw <= probe.headroomCapW, "the fallback respects the grid cap: " + fw + " vs " + probe.headroomCapW);
        }
      }
    }
  }
  assert.ok(capped > 500 && withImport > 500, "the cap was exercised: " + capped);
  assert.ok(fallbackHeld > 40, "fallbacks that hold something were exercised: " + fallbackHeld);
  for (const s of ["OK", "TARGET_AT_RISK", "NO_DATA", "NO_SAFE_CEILING"]) assert.ok((seen[s] ?? 0) > 0, "status exercised: " + s);
});

test("property: more demand never lowers the needed setpoint or brings the finish forward; more solar, a higher limit and more time never raise it; a limit that does not bind changes nothing", () => {
  const rand = rng(1812);
  const scale = (h: HouseholdInput, kd: number, ks: number): HouseholdInput => ({
    ...h,
    demandNowW: h.demandNowW == null ? h.demandNowW : h.demandNowW * kd, demandProfile: h.demandProfile ? h.demandProfile.map((q) => ({ ...q, watts: q.watts * kd })) : h.demandProfile,
    solarNowW: h.solarNowW == null ? h.solarNowW : h.solarNowW * ks, solarProfile: h.solarProfile ? h.solarProfile.map((q) => ({ ...q, watts: q.watts * ks })) : h.solarProfile,
  });
  const rank = (d: GentleDecision) => (d.status === "OK" || d.status === "DEGRADED" ? 0 : d.status === "TARGET_AT_RISK" ? 1 : 2);
  let demandPairs = 0;
  let solarPairs = 0;
  let limitPairs = 0;
  let timePairs = 0;
  let neutral = 0;
  let strictDemand = 0;
  for (let n = 0; n < 3000; n++) {
    const i0 = householdCase(rand);
    const h = i0.household;
    if (!h || typeof h.gridImportLimitW !== "number") continue;
    const i: GentleInput = { ...i0, currentSetpointW: null, lastChangeElapsedMin: null, changesUsed: 0, policy: { unknownDemandPolicy: "ASSUME_PROVISIONAL", fallbackPolicy: "NONE" }, params: undefined };
    const a = planGentle(i);
    if (!PLANNING.has(a.status) || a.headroomCapW === null) continue;
    // more demand
    const hd = planGentle({ ...i, household: scale(h, 1.3, 1) });
    if (PLANNING.has(hd.status)) {
      demandPairs++;
      assert.ok((hd.headroomCapW as number) <= (a.headroomCapW as number), "more demand: a cap no higher");
      assert.ok(inf(hd.neededW) >= inf(a.neededW), "more demand never lowers the needed setpoint: " + hd.neededW + " vs " + a.neededW);
      assert.ok(inf(hd.finishInMin) >= inf(a.finishInMin) - 1e-6, "more demand never brings the finish forward: " + hd.finishInMin + " vs " + a.finishInMin);
      assert.ok(rank(hd) >= rank(a), "more demand never improves the status");
      assert.ok((hd.setpointW as number) <= (a.setpointW as number), "more demand never raises the recommended setpoint");
      if ((hd.headroomCapW as number) < (a.headroomCapW as number)) strictDemand++;
    } else assert.ok(hd.status === "NO_SAFE_CEILING", "the only other outcome of more demand: no safe setpoint left");
    // more solar
    const hs = planGentle({ ...i, household: scale(h, 1, 1.5) });
    assert.ok(PLANNING.has(hs.status));
    solarPairs++;
    assert.ok((hs.headroomCapW as number) >= (a.headroomCapW as number), "more solar: a cap no lower");
    assert.ok(inf(hs.neededW) <= inf(a.neededW), "more solar never raises the needed setpoint");
    assert.ok(inf(hs.finishInMin) <= inf(a.finishInMin) + 1e-6, "more solar never delays the finish");
    assert.ok(rank(hs) <= rank(a));
    // a higher limit
    const hl = planGentle({ ...i, household: { ...h, gridImportLimitW: h.gridImportLimitW + 1000 } });
    limitPairs++;
    assert.ok((hl.headroomCapW as number) >= (a.headroomCapW as number));
    assert.ok(inf(hl.neededW) <= inf(a.neededW));
    assert.ok(rank(hl) <= rank(a));
    // more time: a smaller buffer
    if (i.bufferMin >= 5) {
      const ht = planGentle({ ...i, bufferMin: i.bufferMin - 5 });
      if (PLANNING.has(ht.status)) {
        timePairs++;
        assert.ok((ht.setpointW as number) <= (a.setpointW as number), "more time never raises the setpoint: " + ht.setpointW + " vs " + a.setpointW);
        assert.ok(rank(ht) <= rank(a));
        assert.equal(ht.headroomCapW, a.headroomCapW, "the cap does not depend on the buffer");
      }
    }
    // a limit so high it cannot bind, or none at all: exactly the v1 numbers
    const v1 = planGentle({ ...i, household: undefined });
    for (const big of [{ ...h, gridImportLimitW: 1e9 }, { ...h, gridImportLimitW: null }] as HouseholdInput[]) {
      const g = planGentle({ ...i, household: big });
      neutral++;
      // v3 G3: an ASSUMED demand (an explicit option) turns an OK into DEGRADED; every number is still the v1 number
      for (const k of ["status", "setpointW", "neededW", "finishInMin", "marginMin", "change", "ceilingW", "suggestedBufferMin"] as const) assert.deepEqual(k === "status" && g.status === "DEGRADED" ? "OK" : g[k], v1[k], k + " with a limit that cannot bind");
    }
  }
  assert.ok(demandPairs > 300 && solarPairs > 300 && limitPairs > 300 && timePairs > 200 && neutral > 600 && strictDemand > 100, [demandPairs, solarPairs, limitPairs, timePairs, neutral, strictDemand].join("/"));
});

// ---- the household closed loop ---------------------------------------------------------------------------------------------------

test("household closed loop: at least 300 seeded scenarios, demand and solar that differ from the forecast, a physical grid limit that clips the charge; safety asserted, reach asserted where the forecast holds, the misses REPORTED", () => {
  const N = 360;
  const kinds = new Set<string>();
  const stat = (m: Record<string, number>, k: string, by = 1) => { m[k] = (m[k] ?? 0) + by; };
  const c: Record<string, number> = {};
  const byKind: Record<string, { n: number; margin: number; reached: number; over: number; clipped: number }> = {};
  let ticksChecked = 0;
  let jumpsSeen = 0;
  let slewSeen = 0;
  let capTicks = 0;
  let riskByHeadroom = 0;
  let capLowChecked = 0;
  let worstLate = -Infinity;
  const dynPeak: number[] = [];
  const staPeak: number[] = [];
  const dynFin: number[] = [];
  const staFin: number[] = [];
  let both = 0;
  let dynNoLater = 0;
  let dynReach = 0;
  let staReach = 0;
  let dynOver = 0;
  let staOver = 0;
  let staOverAll = 0;
  let dynOverAll = 0;
  let comparable = 0;
  let violationsOutsideModel = 0;
  for (let id = 0; id < N; id++) {
    const sc = makeHouseholdScenario(id);
    const hs = sc.hh;
    const run = runHouseholdLoop(sc);
    const f = feasibilityHH(sc);
    const key = hs.demandKind + "/" + hs.solarKind;
    kinds.add(key);
    const k = (byKind[key] ??= { n: 0, margin: 0, reached: 0, over: 0, clipped: 0 });
    k.n++;
    if (run.overLimitMin > 0) k.over++;
    if (run.clippedMin > 0) k.clipped++;
    const p = { ...DEFAULT_GENTLE_PARAMS, replanMin: sc.replanMin, maxDecreaseStepW: 1000, ...sc.params };
    // v3 G2: solar is not inside the hard limit, so a solar that falls short of its forecast no longer excuses a crossing: only demand above the forecast and its margin does
    const modelHolds = hs.demandKind !== "exceeds";
    let bound = false;
    for (const tk of run.ticks) {
      const d = tk.decision;
      ticksChecked++;
      assert.equal(d.targetSocPct, sc.targetSocPct, "the target is never lowered");
      assert.equal(d.guarantee, "NONE");
      assert.equal(d.actuationSupported, false);
      if (d.limitedBy === "GRID_HEADROOM") { bound = true; capTicks++; }
      if (d.status === "TARGET_AT_RISK" && d.limitedBy === "GRID_HEADROOM") riskByHeadroom++;
      if (d.setpointW !== null) {
        assert.equal(d.setpointW % p.stepW, 0);
        assert.ok(d.setpointW >= p.minW && d.setpointW <= (d.ceilingW as number) && d.setpointW <= sc.ceilW);
        assert.ok(d.headroomCapW !== null && d.setpointW <= d.headroomCapW, "never above the grid cap: scenario " + id + " t=" + tk.t + " " + d.setpointW + " vs " + d.headroomCapW);
        const imp = (d.household as { projectedImportW: number | null }).projectedImportW;
        assert.ok(imp !== null && imp <= hs.gridLimitW + 1e-6, "pessimistic import inside the limit");
      }
      if (d.headroomCapW !== null && hs.demandKind !== "exceeds" && PLANNING.has(d.status)) {
        capLowChecked++;
        assert.ok(d.headroomCapW >= hs.capLowW - 1e-9, "the controller's cap is at least the independently derived lower bound: " + d.headroomCapW + " vs " + hs.capLowW + " (scenario " + id + ")");
      }
      if (d.fallback.applied) assert.equal(d.setpointW, null);
    }
    // changes
    let ordinary = 0;
    for (let q = 0; q < run.changes.length; q++) {
      const ch = run.changes[q] as (typeof run.changes)[number];
      const prev = q > 0 ? (run.changes[q - 1] as (typeof run.changes)[number]) : null;
      if (ch.kind !== "START" && ch.code !== "ABOVE_CEILING" && ch.code !== "ABOVE_HEADROOM") ordinary++;
      assert.ok(ch.toW <= sc.ceilW);
      if (ch.code === "DECREASE_SAVING") {
        assert.ok((ch.fromW as number) - ch.toW <= 1000 + 1e-9, "the slew limit holds: " + ((ch.fromW as number) - ch.toW));
        assert.ok(prev !== null && ch.t - prev.t >= p.dwellMin, "no saving-decrease inside the dwell");
        assert.ok((ch.fromW as number) - ch.toW >= p.hysteresisW - 1e-9, "a saving-decrease saves at least the hysteresis");
      }
      if (ch.kind === "INCREASE" && ch.toW - (ch.fromW as number) > 1000) jumpsSeen++;
    }
    assert.ok(ordinary <= p.maxChanges, "within the changes budget: " + ordinary + " <= " + p.maxChanges + " (scenario " + id + ")");
    slewSeen += run.slewLimited;
    assert.equal(run.jumps, run.changes.filter((x) => x.kind === "INCREASE" && x.toW - (x.fromW as number) > 1000).length, "every jump is flagged and counted");
    // safety where the model's pessimism holds: demand under the forecast or inside the margin, solar at or above the forecast or absent
    if (modelHolds) assert.equal(run.overLimitMin, 0, "scenario " + id + " (" + key + ") exceeded the grid limit for " + run.overLimitMin + " min");
    else if (run.overLimitMin > 0) violationsOutsideModel++;
    // reaching the target
    const reached = run.reachedTolMin !== null && run.reachedTolMin <= run.deadlineMin;
    if (sc.kind === "in-band" && f === "margin") {
      k.margin++;
      if (reached) k.reached++;
      else if (modelHolds) worstLate = Math.max(worstLate, (run.reachedTolMin ?? Infinity) - run.deadlineMin);
      if (modelHolds) assert.ok(reached, "feasible with margin, forecast holds, but missed: scenario " + id + " (" + key + ") reached " + run.reachedTolMin + " deadline " + run.deadlineMin);
    }
    // what the true battery cannot do even at the full ceiling is flagged, not hidden (a grid cap only makes it harder)
    const fv1 = feasibility(sc);
    if (fv1 === "infeasible" || fv1 === "buffer") {
      stat(c, "cannot");
      const flagged = run.ticks.some((tk) => tk.decision.status === "TARGET_AT_RISK" || tk.decision.status === "TARGET_UNREACHABLE" || tk.decision.status === "NO_SAFE_CEILING");
      if (!flagged) stat(c, "notFlagged");
    }
    const stAll = runStaticHH(sc);
    if (stAll.overLimitMin > 0) staOverAll++;
    if (run.overLimitMin > 0) dynOverAll++;
    // the static planner in the same world (default parameters, forecast holds, feasible with margin)
    if (sc.kind === "in-band" && f === "margin" && modelHolds && sc.paramVariant === "default") {
      const st = runStaticHH(sc);
      comparable++;
      dynPeak.push(run.peakW);
      staPeak.push(st.rateW);
      dynOver += run.overLimitMin > 0 ? 1 : 0;
      staOver += st.overLimitMin > 0 ? 1 : 0;
      if (reached) dynReach++;
      if (st.reachedTolMin !== null && st.reachedTolMin <= run.deadlineMin) staReach++;
      if (run.reachedTolMin !== null && st.reachedTolMin !== null) {
        both++;
        if (run.reachedTolMin <= st.reachedTolMin) dynNoLater++;
        dynFin.push(run.deadlineMin - run.reachedTolMin);
        staFin.push(run.deadlineMin - st.reachedTolMin);
      }
    }
  }
  const mean = (a: number[]) => (a.length === 0 ? NaN : a.reduce((x, y) => x + y, 0) / a.length);
  const sd = (a: number[]) => Math.sqrt(mean(a.map((x) => (x - mean(a)) ** 2)));
  const pct = (a: number, b: number) => (b === 0 ? "n/a" : ((100 * a) / b).toFixed(0) + " %");
  let marginAll = 0;
  let reachedAll = 0;
  let exMargin = 0;
  let exReached = 0;
  let exOver = 0;
  let exN = 0;
  for (const [key, v] of Object.entries(byKind)) {
    marginAll += v.margin;
    reachedAll += v.reached;
    if (key.startsWith("exceeds")) { exMargin += v.margin; exReached += v.reached; exOver += v.over; exN += v.n; }
  }
  console.log("[gentle household] " + N + " seeded scenarios, " + ticksChecked + " controller ticks, " + kinds.size + " demand/solar kinds; ticks limited by the grid headroom " + capTicks + "; at risk because of the headroom " + riskByHeadroom + "; the independent cap bound checked on " + capLowChecked + " ticks");
  console.log("[gentle household] the true battery cannot make the deadline even at the full ceiling in " + (c.cannot ?? 0) + " scenarios; the controller flagged AT_RISK, UNREACHABLE or no safe setpoint in all but " + (c.notFlagged ?? 0));
  console.log("[gentle household] feasible with margin under the cap, all kinds: " + reachedAll + " of " + marginAll + " reached by the deadline (" + pct(reachedAll, marginAll) + ")");
  console.log("[gentle household] demand EXCEEDS the forecast beyond the margin (spikes), " + exN + " scenarios: reached by the deadline " + exReached + " of " + exMargin + " feasible-with-margin runs (miss rate " + pct(exMargin - exReached, exMargin) + "); the grid limit was crossed by the setpoint in " + exOver + " of " + exN + " scenarios; outside the model's pessimism the limit was crossed in " + violationsOutsideModel + " scenarios in all");
  for (const [key, v] of Object.entries(byKind).sort()) console.log("[gentle household]   " + key.padEnd(22) + " n=" + String(v.n).padStart(3) + " feasible " + String(v.margin).padStart(3) + " reached " + String(v.reached).padStart(3) + " limit crossed " + String(v.over).padStart(2) + " clipped " + String(v.clipped).padStart(2));
  console.log("[gentle household] slew-limited decreases " + slewSeen + ", deadline jumps " + jumpsSeen + "; worst lateness where the forecast holds: " + (worstLate === -Infinity ? "none" : worstLate + " min"));
  console.log("[gentle vs static, household] forecast-holds feasible runs (" + comparable + "): reached by the deadline dynamic " + dynReach + ", static " + staReach + "; setpoint above the grid limit with the true load: dynamic " + dynOver + " runs, static " + staOver + " runs");
  console.log("[gentle vs static, household] all " + N + " scenarios, setpoint above the grid limit with the true load at some minute: dynamic " + dynOverAll + " runs (all with demand or solar outside its forecast and margin), static fixed rate " + staOverAll + " runs");
  console.log("[gentle vs static, household] dynamic finished no later than static in " + dynNoLater + " of " + both + " (" + pct(dynNoLater, both) + "); peak setpoint dynamic mean " + mean(dynPeak).toFixed(0) + " W, static mean " + mean(staPeak).toFixed(0) + " W; minutes before the deadline: dynamic mean " + mean(dynFin).toFixed(1) + " (sd " + sd(dynFin).toFixed(1) + "), static mean " + mean(staFin).toFixed(1) + " (sd " + sd(staFin).toFixed(1) + ")");
  assert.ok(N >= 300 && kinds.size === 12, "every demand/solar kind: " + kinds.size);
  assert.ok(marginAll >= 150 && capTicks > 200 && riskByHeadroom > 30, "the headroom path was exercised: " + [marginAll, capTicks, riskByHeadroom].join("/"));
  assert.ok(capLowChecked > 2000);
  assert.ok(exN >= 100 && exMargin >= 40, "the exceeding-forecast scenarios exist and are reported: " + exN + "/" + exMargin);
  assert.ok((c.cannot ?? 0) >= 20, "scenarios the true battery cannot make are present: " + c.cannot);
  assert.equal(c.notFlagged ?? 0, 0, "everything the true battery cannot do at the full ceiling was flagged AT_RISK, UNREACHABLE or no safe setpoint");
  assert.ok(slewSeen > 20 && jumpsSeen > 5, "the slew and the jump flag were exercised: " + slewSeen + "/" + jumpsSeen);
  assert.ok(dynReach >= staReach, "the controller reaches the deadline at least as often as the static rate");
  assert.equal(dynOver, 0, "the controller never put the setpoint over the grid limit where the forecast holds");
  assert.ok(comparable >= 60, "enough comparable runs: " + comparable);
  void staOver;
});

test("noisy demand and solar inputs cannot make the setpoint flap: where the headroom does not bind the plan is identical to the exact-input plan, where it binds a decrease is only followed by an increase inside the dwell when the deadline needs it", () => {
  let identical = 0;
  let bindingRuns = 0;
  let reversals = 0;
  let unneeded = 0;
  let atRiskRises = 0;
  let noisyRuns = 0;
  let changesNoisy = 0;
  let changesClean = 0;
  for (let id = 0; id < 360; id++) {
    const sc = makeHouseholdScenario(id);
    const clean = runHouseholdLoop(sc);
    const touched = (r: typeof clean) => r.ticks.some((tk) => tk.decision.limitedBy === "GRID_HEADROOM" || tk.decision.codes.some((cd) => cd === "HEADROOM_BELOW_MIN" || cd === "HOUSEHOLD_UNUSABLE" || cd === "HOUSEHOLD_INVALID"));
    changesClean += clean.changes.length;
    for (let seed = 0; seed < 2; seed++) {
      const nr = rng(900 + id * 7 + seed);
      const noisy = runHouseholdLoop(sc, planGentle, {
        tweak: (h) => ({
          ...h,
          demandNowW: typeof h.demandNowW === "number" ? Math.max(0, h.demandNowW * (1 + 0.5 * (2 * nr() - 1))) : h.demandNowW,
          solarNowW: typeof h.solarNowW === "number" ? Math.max(0, h.solarNowW * (1 + 0.5 * (2 * nr() - 1))) : h.solarNowW,
          demandAgeMin: nr() < 0.2 ? 60 : h.demandAgeMin,
        }),
      });
      noisyRuns++;
      changesNoisy += noisy.changes.length;
      const bound = touched(noisy);
      if (bound) bindingRuns++;
      if (!bound && !touched(clean)) {
        // the headroom never mattered, noisy or clean: the noisy run took exactly the decisions of the run with exact household inputs
        identical++;
        assert.equal(noisy.ticks.length, clean.ticks.length);
        for (let q = 0; q < noisy.ticks.length; q++) {
          const a = noisy.ticks[q] as (typeof noisy.ticks)[number];
          const b = clean.ticks[q] as (typeof noisy.ticks)[number];
          assert.equal(a.decision.setpointW, b.decision.setpointW, "scenario " + id + " seed " + seed + " tick " + a.t);
          assert.equal(a.decision.change, b.decision.change);
          assert.equal(a.decision.status, b.decision.status);
        }
      }
      // reversals inside the dwell
      const p = { ...DEFAULT_GENTLE_PARAMS, replanMin: sc.replanMin, maxDecreaseStepW: 1000, ...sc.params };
      for (let q = 1; q < noisy.changes.length; q++) {
        const prev = noisy.changes[q - 1] as (typeof noisy.changes)[number];
        const cur = noisy.changes[q] as (typeof noisy.changes)[number];
        if (prev.kind === "DECREASE" && cur.kind === "INCREASE" && cur.t - prev.t < p.dwellMin) {
          reversals++;
          const tk = noisy.ticks.find((x) => x.t === cur.t) as (typeof noisy.ticks)[number];
          // v3 G1: a rise toward the CEILING in an at-risk state (the limit does not bind) is a deadline need and is never held; only a binding cap's
          // recovery waits, so only that case can be an unneeded reversal
          if (tk.decision.neededW === null && tk.decision.limitedBy === "GRID_HEADROOM") unneeded++;
          else if (tk.decision.neededW === null) atRiskRises++;
        }
      }
    }
  }
  console.log("[gentle noise] " + noisyRuns + " runs with 50 % noise on the demand and solar readings and 20 % stale demand: " + identical + " never limited by the headroom, neither noisy nor clean, and then identical to the run with exact household input; " + bindingRuns + " limited by it at some tick; decrease-then-increase inside the dwell " + reversals + " times, of which not needed for the deadline " + unneeded + " (and " + atRiskRises + " rises toward the ceiling in an at-risk state, a deadline need that is never held); setpoint changes noisy " + changesNoisy + " vs clean " + changesClean);
  assert.ok(identical >= 150, "enough runs where the headroom never bound: " + identical);
  assert.ok(bindingRuns >= 50, "and enough where it did: " + bindingRuns);
  assert.equal(unneeded, 0, "no flapping: an increase right after a decrease only when the deadline needs it");
  assert.ok(changesNoisy / noisyRuns <= 1.5 * (changesClean / 360) + 0.5, "noise does not multiply the changes: " + changesNoisy / noisyRuns + " per run vs " + changesClean / 360 + " clean");
});

test("closed loop fallbacks: with stale SOC readings a held setpoint never exceeds the ceiling or the grid cap, whatever the policy", () => {
  let held = 0;
  let nones = 0;
  let ticksWithFallback = 0;
  for (const policy of ["KEEP_CURRENT", "USE_STATIC_PLAN", "NONE"] as const) {
    for (let id = 0; id < 120; id++) {
      const sc0 = makeHouseholdScenario(id);
      const sc = { ...sc0, staleProb: 0.5 };
      const probeCap = (i: GentleInput) => planGentle({ ...i, socPct: 5, socAgeMin: 0, targetSocPct: 100 });
      const run = runHouseholdLoop(sc, (i) => {
        const d = planGentle(i);
        if (d.fallback.applied) {
          ticksWithFallback++;
          const fw = d.fallback.setpointW;
          if (fw === null) nones++;
          else {
            held++;
            const pr = probeCap(i);
            assert.ok(fw <= sc.ceilW, "within the ceiling");
            if (pr.headroomCapW !== null && pr.status !== "NO_DATA") assert.ok(fw <= pr.headroomCapW, "within the grid cap");
            if (policy === "NONE") assert.fail("NONE never holds anything");
          }
        }
        return d;
      }, { policy: { fallbackPolicy: policy }, staticRateW: 4000 });
      assert.ok(run.ticks.every((tk) => tk.decision.setpointW === null || tk.decision.fallback.applied === false));
    }
  }
  assert.ok(ticksWithFallback > 300 && held > 100 && nones > 50, [ticksWithFallback, held, nones].join("/"));
});

test("static: the household, fallback, slew and provenance code is pure data: still no service call, write, clock, randomness or class; guarantee and actuation are constants; every new function is exported pure", () => {
  const raw = readFileSync(new URL("../src/gentleController.ts", import.meta.url), "utf8");
  const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'])\/\/.*$/gm, "$1").replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
  for (const banned of [/callService/, /\bhass\b/i, /\bfetch\s*\(/, /\bDate\b/, /Math\.random/, /setTimeout|setInterval/, /\bwrite/i, /turn_on|set_value|press|modbus|register/i, /\bimport\s*\(/, /\bclass\s/, /\basync\b|\bawait\b|\bPromise\b/, /\bprocess\b/, /\bwindow\b|\bdocument\b|\bglobalThis\b/, /localStorage|sessionStorage|indexedDB/, /\bthis\b/, /\bnew\s+(Date|Function|Worker)/, /\beval\b/, /require\s*\(/]) {
    assert.doesNotMatch(code, banned, "matches " + banned);
  }
  assert.equal((raw.match(/guarantee: "NONE"/g) ?? []).length, 2, "the type and the one place it is set, both NONE");
  assert.doesNotMatch(raw, /guarantee:\s*(true|"GUARANTEED"|"ALWAYS")/);
  assert.equal((raw.match(/actuationSupported:\s*false/g) ?? []).length, 2);
  assert.doesNotMatch(raw, /actuationSupported:\s*true/);
  assert.equal((raw.match(/^export const [A-Z_]+ =/gm) ?? []).length >= 6, true);
  // frozen constants: nobody can lower a limit at run time
  assert.ok(Object.isFrozen(DEFAULT_GENTLE_PARAMS) && Object.isFrozen(DEFAULT_GENTLE_POLICY) && Object.isFrozen(GENTLE_RECOMMENDED_PARAMS) && Object.isFrozen(PARAM_PROVENANCE));
  // pure: the same input twice gives the same answer, and the input is untouched
  const i: GentleInput = { ...hbase, household: { gridImportLimitW: 5000, demandProfile: flat(1000) } };
  const snap = JSON.stringify(i);
  assert.deepEqual(planGentle(i), planGentle(i));
  assert.equal(JSON.stringify(i), snap);
  // the README says it plainly
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  assert.match(readme, /does not guarantee|NOT guaranteed|not guaranteed/);
  assert.match(readme, /100 percent|100 %/);
});

// =================================================================================================================================
// v3 review fixes (independent review of the read-only model). Each section names the finding it closes: G1 recovery flag, G2 solar in the
// hard limit, G3 unknown-demand default, G4 ages, G5 setpoint basis, G6 taper shapes, G7 minors. Everything is simulated, never measured.
// =================================================================================================================================

test("[v3 G1] an increase toward the ceiling in an at-risk or deadline-passed state is never held by hysteresis or dwell when the grid limit does not bind; a binding cap still waits like a saving", () => {
  // The reviewer's case: a known limit that does not bind (30000 W), a dip makes the needed rate unknown (the target is out of reach at the
  // ceiling), the setpoint in force is just under the ceiling. With household input the old flag held it (400 W < the 500 W hysteresis).
  const risk: Partial<GentleInput> = { targetSocPct: 90, socPct: 50, elapsedMin: 160, currentSetpointW: 4600, lastChangeElapsedMin: 155, changesUsed: 0 };
  const NB: HouseholdInput = { gridImportLimitW: 30000, demandProfile: flat(500) };
  const free = plan({ ...risk, bufferMin: 60 });
  assert.equal(free.status, "TARGET_AT_RISK");
  assert.equal(free.neededW, null);
  assert.equal(free.change, "INCREASE", "without household input the increase goes through");
  assert.equal(free.setpointW, 5000);
  for (const [name, over] of [["short of the hysteresis", {}], ["inside the dwell", { currentSetpointW: 3000 }], ["both", { currentSetpointW: 4600, lastChangeElapsedMin: 159 }]] as [string, Partial<GentleInput>][]) {
    const d = hplan(NB, { ...risk, ...over });
    const v1 = plan({ ...risk, ...over, bufferMin: 60 });
    assert.equal(d.status, "TARGET_AT_RISK", name);
    assert.equal(d.limitedBy, "CEILING", name);
    assert.equal(d.change, "INCREASE", name + ": " + d.codes.join(","));
    assert.equal(d.setpointW, 5000, name);
    assert.ok(d.codes.includes("INCREASE_FOR_DEADLINE"), name);
    assert.ok(!d.codes.includes("HELD_HYSTERESIS") && !d.codes.includes("HELD_DWELL"), name);
    assert.equal(d.setpointW, v1.setpointW, name + ": the household answer equals the v1 answer where the limit does not bind");
    assert.equal(d.change, v1.change, name);
  }
  // the deadline has passed but the window is still open: the same rule
  const late: Partial<GentleInput> = { targetSocPct: 80, socPct: 60, elapsedMin: 310, currentSetpointW: 4600, lastChangeElapsedMin: 305 };
  const dp = hplan(NB, late);
  assert.equal(dp.status, "DEADLINE_PASSED");
  assert.equal(dp.change, "INCREASE", dp.codes.join(","));
  assert.equal(dp.setpointW, 5000);
  assert.equal(dp.change, plan({ ...late, bufferMin: 60 }).change);
  // an exhausted changes budget still holds (as in v1), and a fall is immediate whatever the limit
  assert.ok(hplan(NB, { ...risk, changesUsed: 6 }).codes.includes("HELD_BUDGET"));
  const fell = hplan({ gridImportLimitW: 30000, demandProfile: flat(500) }, { ...risk, currentSetpointW: 5600, ceilings: [{ name: "battery_max_charge", watts: 4000 }] });
  assert.equal(fell.change, "DECREASE");
  assert.ok(fell.codes.includes("ABOVE_CEILING"));
  // a BINDING cap (3300 W): the rise of a recovering cap waits for the hysteresis and the dwell, at risk and after the deadline alike
  const BIND: HouseholdInput = { gridImportLimitW: 4500, demandProfile: flat(1000) };
  const bind = hplan(BIND, { ...risk, currentSetpointW: 3000, lastChangeElapsedMin: 120 });
  assert.equal(bind.limitedBy, "GRID_HEADROOM");
  assert.equal(bind.change, "NONE");
  assert.ok(bind.codes.includes("HELD_HYSTERESIS"));
  assert.equal(hplan(BIND, { ...risk, currentSetpointW: 2500, lastChangeElapsedMin: 155 }).codes.includes("HELD_DWELL"), true);
  assert.equal(hplan(BIND, { ...risk, currentSetpointW: 2500, lastChangeElapsedMin: 120 }).change, "INCREASE");
  const bindLate = hplan(BIND, { ...late, currentSetpointW: 3000, lastChangeElapsedMin: 250 });
  assert.equal(bindLate.status, "DEADLINE_PASSED");
  assert.equal(bindLate.limitedBy, "GRID_HEADROOM");
  assert.equal(bindLate.change, "NONE");
  assert.ok(bindLate.codes.includes("HELD_HYSTERESIS"));
  // a limit that is KNOWN but far above (so it never binds) and the same state with no household group agree tick for tick
  let n = 0;
  for (const cur of [3000, 3500, 4000, 4400, 4600, 4800, 4900]) for (const since of [1, 10, 29, 31, 60]) {
    const a = hplan(NB, { ...risk, currentSetpointW: cur, lastChangeElapsedMin: 160 - since });
    const b = plan({ ...risk, currentSetpointW: cur, lastChangeElapsedMin: 160 - since, bufferMin: 60 });
    assert.equal(a.setpointW, b.setpointW, cur + "/" + since);
    assert.equal(a.change, b.change, cur + "/" + since);
    n++;
  }
  assert.equal(n, 35);
});

test("[v3 G3] unknown demand under a KNOWN grid limit: the default is FALLBACK (nothing guessed, no recommendation); the provisional assumption is an explicit option and its status is DEGRADED, never OK", () => {
  assert.equal(DEFAULT_GENTLE_POLICY.unknownDemandPolicy, "FALLBACK");
  assert.equal(PARAM_PROVENANCE.unknownDemandPolicy?.value, "FALLBACK");
  // a known limit, no demand at all, the default policy: the guessed constant is not used
  for (const h of [{ gridImportLimitW: 6000 }, { gridImportLimitW: 6000, demandNowW: 500, demandAgeMin: 0 }, { gridImportLimitW: 6000, demandProfile: [{ fromInMin: 20, watts: 400 }] }] as HouseholdInput[]) {
    const d = hplan(h, { currentSetpointW: 3000, lastChangeElapsedMin: 0, elapsedMin: 5 });
    assert.equal(d.status, "NO_DATA", JSON.stringify(h));
    assert.equal(d.setpointW, null, "no guessed 2000 W under a known safety limit");
    assert.equal(d.changeRecommended, false);
    assert.ok(d.codes.includes("HOUSEHOLD_UNUSABLE"));
    assert.ok(!d.codes.includes("ASSUMED_DEMAND"));
    assert.equal(d.household, null);
    assert.equal(d.fallback.applied, true);
    assert.equal(d.fallback.setpointW, null, "the grid headroom cannot be checked, so even KEEP_CURRENT recommends nothing");
  }
  // the assumption is still available, but only when asked for, and it is DEGRADED, not OK
  const opt: Partial<GentleInput> = { policy: { unknownDemandPolicy: "ASSUME_PROVISIONAL" } };
  const a = hplan({ gridImportLimitW: 9000 }, opt);
  assert.equal(a.status, "DEGRADED");
  assert.notEqual(a.status, "OK");
  assert.ok(a.codes.includes("ASSUMED_DEMAND"));
  assert.ok(a.setpointW !== null && a.setpointW <= (a.headroomCapW as number));
  assert.equal(hplan({ gridImportLimitW: 6000 }, opt).headroomCapW, 3600, "the explicit option keeps its arithmetic: 6000 - 2000 x 1.2");
  assert.equal(a.headroomCapW, 6600);
  assert.equal(a.household?.demandBasis, "ASSUMED");
  assert.match(a.reasons.join(" "), /DEGRADED/);
  assert.match(a.reasons.join(" "), /assumed, not measured/);
  assert.ok(a.provisionalInUse.some((x) => x.name === "assumedDemandW" && x.kind === "MEASURED_REQUIRED" && x.source === "DEFAULT"));
  assert.ok(a.provisionalInUse.some((x) => x.name === "unknownDemandPolicy" && x.value === "ASSUME_PROVISIONAL" && x.source === "CALLER"));
  assert.equal(a.guarantee, "NONE");
  // a worse status is not softened: at risk stays at risk (and still carries the assumed-demand code)
  const risk = hplan({ gridImportLimitW: 5000 }, { ...opt, targetSocPct: 100, socPct: 40 });
  assert.ok(risk.status === "TARGET_AT_RISK" || risk.status === "TARGET_UNREACHABLE", risk.status);
  assert.ok(risk.codes.includes("ASSUMED_DEMAND"));
  // a forecast from now covers the window under either policy: OK, no degradation
  for (const policy of ["FALLBACK", "ASSUME_PROVISIONAL"] as const) {
    const ok = hplan({ gridImportLimitW: 7000, demandProfile: flat(1000) }, { policy: { unknownDemandPolicy: policy } });
    assert.equal(ok.status, "OK", policy);
    assert.ok(!ok.codes.includes("ASSUMED_DEMAND"));
  }
  // without a known limit demand is irrelevant: v1 numbers, status OK
  assert.equal(hplan({ demandProfile: undefined }).status, "OK");
  // a sweep: a known limit and no usable demand under the default policy never yields a setpoint, whatever the state
  const rand = rng(31337);
  let swept = 0;
  for (let n = 0; n < 600; n++) {
    const i = householdCase(rand);
    const lim = 1500 + Math.floor(rand() * 9000);
    const d = planGentle({ ...i, socPct: 5 + Math.floor(rand() * 80), socAgeMin: 1, ceilings: [{ name: "owner_maximum", watts: 5000 }], policy: undefined, household: { gridImportLimitW: lim } });
    if (d.status === "NOTHING_TO_CHARGE" || d.status === "INVALID") continue;
    swept++;
    assert.equal(d.setpointW, null, "no guessed demand: " + d.status);
    assert.ok(d.status === "NO_DATA" || d.status === "DEADLINE_PASSED", d.status);
  }
  assert.ok(swept > 300, "swept " + swept);
});

const HP = (age: unknown, over: Partial<HouseholdInput> = {}) => planGentle({ ...hbase, policy: { setpointBasis: "GRID_AC" }, household: { gridImportLimitW: 7000, demandProfile: flat(1000), demandProfileAgeMin: age as number, ...over } });
const CE = (cs: NamedCeiling[], over: Partial<GentleInput> = {}) => plan({ ceilings: cs, ...over });

test("[v3 G4a] a forecast needs a fresh age: a stale, missing or invalid age counts as unknown (fail closed), never a covered window", () => {
  // forecast age: exactly the limit is fresh, over it, missing, null, negative, NaN and a string are not
  for (const ok of [0, 1, 60, 120]) assert.equal(HP(ok).status, "OK", "age " + ok);
  assert.equal(HP(0).headroomCapW, 5800);
  for (const bad of [121, 600, undefined, null, -1, NaN, "5"]) {
    const d = HP(bad);
    assert.equal(d.status, "NO_DATA", "age " + String(bad));
    assert.equal(d.setpointW, null, "a forecast with no fresh age does not cover the window");
    assert.ok(d.codes.includes("HOUSEHOLD_UNUSABLE") && d.codes.includes("FORECAST_STALE"), String(bad) + ": " + d.codes.join(","));
    assert.equal(d.fallback.applied, true);
    assert.equal(d.fallback.setpointW, null, "the grid headroom cannot be checked");
  }
  // a fresh READING does not rescue a stale forecast (it covers only the first minutes), and an assumed demand degrades the status
  assert.equal(HP(500, { demandNowW: 600, demandAgeMin: 0 }).status, "NO_DATA");
  const assumed = planGentle({ ...hbase, policy: { unknownDemandPolicy: "ASSUME_PROVISIONAL" }, household: { gridImportLimitW: 9000, demandProfile: flat(1000), demandProfileAgeMin: 500 } });
  assert.equal(assumed.status, "DEGRADED");
  assert.equal(assumed.household?.demandBasis, "ASSUMED");
  assert.ok(assumed.codes.includes("FORECAST_STALE") && assumed.codes.includes("ASSUMED_DEMAND"));
  assert.equal(assumed.household?.demandPeakW, 2400, "the stale forecast's 1000 W is not used: the assumed 2000 W x 1.2");
  assert.equal(planGentle({ ...hbase, params: { maxForecastAgeMin: 300 }, household: { gridImportLimitW: 7000, demandProfile: flat(1000), demandProfileAgeMin: 300 } }).status, "OK");
  assert.ok(hplan({ gridImportLimitW: 7000, demandProfile: flat(1000) }).provisionalInUse.some((x) => x.name === "maxForecastAgeMin" && x.kind === "PROVISIONAL" && x.source === "DEFAULT"));
  assert.ok(!plan().provisionalInUse.some((x) => x.name === "maxCeilingAgeMin" || x.name === "maxForecastAgeMin"), "only where they act");
});

test("[v3 G4b] the age limits are validated parameters with conservative defaults", () => {
  assert.equal(DEFAULT_GENTLE_PARAMS.maxForecastAgeMin, 120);
  assert.equal(DEFAULT_GENTLE_PARAMS.maxCeilingAgeMin, 60);
  assert.equal(DEFAULT_GENTLE_PARAMS.maxGridLimitAgeMin, 60);
  for (const params of [{ maxForecastAgeMin: 0 }, { maxForecastAgeMin: -5 }, { maxForecastAgeMin: 1441 }, { maxForecastAgeMin: NaN }, { maxCeilingAgeMin: 0 }, { maxCeilingAgeMin: 5000 }, { maxGridLimitAgeMin: 0 }, { maxGridLimitAgeMin: 1441 }]) assert.equal(plan({ params }).status, "INVALID", JSON.stringify(params));
  for (const params of [{ maxForecastAgeMin: 1 }, { maxForecastAgeMin: 1440 }, { maxCeilingAgeMin: 1440 }, { maxGridLimitAgeMin: 1 }]) assert.equal(plan({ params }).status, "OK", JSON.stringify(params));
});

test("[v3 G4c] a stale solar forecast is ignored; a stale or invalid grid limit age makes the household input unusable, which is not the same as no limit", () => {
  // a stale solar forecast is ignored like any untrusted solar
  const sol = (age: unknown) => planGentle({ ...hbase, household: { gridImportLimitW: 4500, demandProfile: flat(1000), demandProfileAgeMin: 0, solarNowW: 2000, solarAgeMin: 0, solarProfile: flat(4000), solarProfileAgeMin: age as number, solarConfidence: 0.5 } });
  assert.ok(!sol(0).codes.includes("SOLAR_IGNORED"));
  for (const bad of [121, undefined, null, NaN]) assert.ok(sol(bad).codes.includes("SOLAR_IGNORED"), "solar forecast age " + String(bad));
  // the grid limit: no age is a static limit (accepted); an age is enforced; a limit that was GIVEN but is stale is not "no limit"
  assert.equal(HP(0, { gridImportLimitAgeMin: 60 }).status, "OK");
  assert.equal(HP(0, { gridImportLimitAgeMin: undefined }).status, "OK");
  assert.equal(HP(0, { gridImportLimitAgeMin: null }).status, "OK");
  for (const bad of [61, 999, -1, NaN, "x"]) {
    const d = HP(0, { gridImportLimitAgeMin: bad as number });
    assert.equal(d.status, "NO_DATA", "limit age " + String(bad));
    assert.equal(d.setpointW, null);
    assert.ok(d.codes.includes("GRID_LIMIT_STALE") && d.codes.includes("HOUSEHOLD_UNUSABLE"));
    assert.ok(!d.codes.includes("NO_GRID_LIMIT"), "a stale limit is not the same as no limit");
    assert.equal(d.fallback.setpointW, null);
  }
  assert.equal(HP(0, { gridImportLimitAgeMin: 300 }).fallback.applied, true);
  assert.equal(planGentle({ ...hbase, params: { maxGridLimitAgeMin: 300 }, household: { gridImportLimitW: 7000, gridImportLimitAgeMin: 300, demandProfile: flat(1000), demandProfileAgeMin: 0 } }).status, "OK");
  // no limit at all: demand and ages are irrelevant, as before
  assert.equal(planGentle({ ...hbase, household: { demandProfile: flat(1000), demandProfileAgeMin: 9999 } }).status, "OK");
});

test("[v3 G4d] named ceilings with an age: no age is static (v1); a stale ceiling never raises the cap but a stale LOWER one still lowers it; none fresh is NO_SAFE_CEILING, no fallback", () => {
  assert.equal(CE([{ name: "owner_maximum", watts: 5000 }]).ceilingW, 5000);
  assert.equal(CE([{ name: "owner_maximum", watts: 5000, ageMin: 0 }, { name: "battery_max_charge", watts: 6200, ageMin: 60 }]).ceilingW, 5000);
  const lowStale = CE([{ name: "owner_maximum", watts: 5000, ageMin: 0 }, { name: "battery_max_charge", watts: 3000, ageMin: 61 }]);
  assert.equal(lowStale.ceilingW, 3000, "a derated limit that went quiet is not forgotten");
  assert.equal(lowStale.ceilingName, "battery_max_charge");
  assert.ok(lowStale.codes.includes("CEILING_STALE"));
  assert.match(lowStale.reasons.join(" "), /still caps/);
  assert.ok((lowStale.setpointW as number) <= 3000);
  const highStale = CE([{ name: "owner_maximum", watts: 5000, ageMin: 0 }, { name: "battery_max_charge", watts: 9000, ageMin: 500 }]);
  assert.equal(highStale.ceilingW, 5000, "a stale value never raises the cap");
  assert.ok(highStale.codes.includes("CEILING_STALE"));
  const staleOnlyLower = CE([{ name: "owner_maximum", watts: 5000, ageMin: 90 }, { name: "battery_max_charge", watts: 6200, ageMin: 0 }]);
  assert.equal(staleOnlyLower.ceilingW, 5000, "the stale owner maximum is lower than the fresh battery limit, so it caps");
  for (const stale of [[{ name: "a", watts: 5000, ageMin: 61 }], [{ name: "a", watts: 5000, ageMin: NaN }], [{ name: "a", watts: 5000, ageMin: -1 }], [{ name: "a", watts: 5000, ageMin: 90 }, { name: "b", watts: 6000, ageMin: 1000 }]] as NamedCeiling[][]) {
    const d = CE(stale, { currentSetpointW: 3000, policy: { fallbackPolicy: "KEEP_CURRENT" } });
    assert.equal(d.status, "NO_SAFE_CEILING", JSON.stringify(stale));
    assert.equal(d.setpointW, null);
    assert.equal(d.neededW, null);
    assert.ok(d.codes.includes("NO_CEILING") && d.codes.includes("CEILING_STALE"));
    assert.equal(d.fallback.setpointW, null, "no fresh ceiling to check a fallback against");
    assert.match(d.reasons.join(" "), /stale/);
  }
  assert.equal(CE([{ name: "a", watts: 5000, ageMin: 100 }], { params: { maxCeilingAgeMin: 100 } }).status, "OK", "the limit is the owner's parameter");
  // a fresh ceiling and no ages anywhere: never a stale code
  assert.ok(!CE([{ name: "a", watts: 5000, ageMin: 5 }]).codes.includes("CEILING_STALE"));
  assert.ok(!plan().codes.includes("CEILING_STALE"));
  // the exported helper
  const r = G4.effectiveCeiling([{ name: "x", watts: 4000, ageMin: 10 }, { name: "y", watts: 3500, ageMin: 99 }, { name: "z", watts: null }], 60);
  assert.deepEqual({ best: r.best, stale: r.staleNames, caps: r.staleCaps }, { best: { watts: 3500, name: "y" }, stale: ["y"], caps: true });
  assert.equal(G4.effectiveCeiling([{ name: "y", watts: 3500, ageMin: 99 }], 60).best, null);
  assert.ok(CE([{ name: "a", watts: 5000, ageMin: 5 }]).provisionalInUse.some((x) => x.name === "maxCeilingAgeMin"), "listed where it acts");
});

test("[v3 G2a] solar is not inside the hard grid limit by default: the cap is the limit minus the demand peak; crediting solar is an explicit, validated parameter and the bounded solar is shown as information", () => {
  const sol = (conf: number | null, extra: Partial<HouseholdInput> = {}): HouseholdInput => ({ gridImportLimitW: 4500, demandProfile: flat(1000), solarNowW: 2000, solarAgeMin: 1, solarProfile: flat(4000), solarConfidence: conf, ...extra });
  assert.equal(DEFAULT_GENTLE_PARAMS.solarCreditPct, 0);
  assert.equal(PARAM_PROVENANCE.solarCreditPct?.kind, "PROVISIONAL");
  // by default no solar is credited, whatever the confidence: 4500 - 1000 x 1.2 = 3300
  for (const conf of [0, 0.4, 0.5, 1, null]) {
    const d = hplan(sol(conf));
    assert.equal(d.headroomCapW, 3300, "confidence " + conf);
    assert.equal(d.household?.solarCountedMinW, 0, "nothing is credited");
    assert.ok(d.codes.includes("SOLAR_NOT_CREDITED"), "the reason says so");
    assert.match(d.reasons.join(" "), /not counted inside the hard grid limit/);
    assert.ok((d.setpointW as number) <= 3300);
  }
  // the bounded solar is still reported, labelled as information (min of the reading and the scaled forecast)
  assert.equal(hplan(sol(0.4)).household?.solarPotentialMinW, 1600);
  assert.equal(hplan(sol(1)).household?.solarPotentialMinW, 2000);
  assert.equal(hplan(sol(null)).household?.solarPotentialMinW, 0);
  // an explicit credit: 100 % keeps the old arithmetic (4500 - 1200 + 1600), 50 % credits half of it
  const full = hplan(sol(0.4), { params: { solarCreditPct: 100 } });
  assert.equal(full.headroomCapW, 4900);
  assert.equal(full.household?.solarCountedMinW, 1600);
  assert.ok(!full.codes.includes("SOLAR_NOT_CREDITED"));
  assert.equal(hplan(sol(0.4), { params: { solarCreditPct: 50 } }).headroomCapW, 4100);
  assert.equal(hplan(sol(0.4), { params: { solarCreditPct: 50 } }).household?.solarCountedMinW, 800);
  assert.equal(hplan(sol(0.4), { params: { solarCreditPct: 0 } }).headroomCapW, 3300);
  // validated
  for (const solarCreditPct of [-1, 101, NaN, Infinity, "50" as unknown as number]) assert.equal(plan({ params: { solarCreditPct } }).status, "INVALID", String(solarCreditPct));
  for (const solarCreditPct of [0, 1, 50, 100]) assert.equal(plan({ params: { solarCreditPct } }).status, "OK", String(solarCreditPct));
  // without any solar input there is nothing to explain
  assert.ok(!hplan({ gridImportLimitW: 4500, demandProfile: flat(1000) }).codes.includes("SOLAR_NOT_CREDITED"));
  // a plentiful solar reading and forecast never lift the setpoint above the limit minus the demand peak
  for (const w of [500, 3000, 20000]) {
    const d = hplan(sol(1, { solarNowW: w, solarProfile: flat(w) }), { targetSocPct: 100, socPct: 20 });
    assert.ok((d.setpointW as number) <= 3300, "solar " + w + ": " + d.setpointW);
    assert.equal(d.headroomCapW, 3300);
  }
  // the hard cap with solar not counted is a function of limit and demand only: the same cap with and without a solar group
  assert.equal(hplan({ gridImportLimitW: 4500, demandProfile: flat(1000) }).headroomCapW, hplan(sol(0.9)).headroomCapW);
  // the credit is only ever additive and bounded by the reading: a zero reading credits nothing even at 100 %
  assert.equal(hplan(sol(1, { solarNowW: 0 }), { params: { solarCreditPct: 100 } }).headroomCapW, 3300);
});

// A CLOUD scenario: the controller is told it is sunny (a fresh reading of 3000 W and a forecast of the same) but the true solar is a small fraction of that for the whole window.
const cloudScenario = (variant: number) => {
  const base0 = makeHouseholdScenario(5);
  const limit = [6500, 7000, 7500][variant % 3] as number;
  const fcst = [2500, 3000, 3500][Math.floor(variant / 3) % 3] as number;
  const trueFrac = [0, 0.03, 0.1][Math.floor(variant / 9) % 3] as number;
  const nSeg = 8;
  const sc = {
    ...base0, kind: "in-band" as const, targetSocPct: 100, bufferMin: 60, clockDay: { changeAtMin: 0, deltaMin: 0 } as ClockDay, windowStartMin: 22 * 60, windowWallMin: 360, windowRealMin: 360,
    startSocPct: 10, nominalKwh: 30, capacityUpPct: 6, trueCapacityKwh: 30 * 1.03, trueEff: 0.95, trueTaper: { startSocPct: 92, endFraction: 0.2 },
    ceilings: [{ name: "owner_maximum", watts: 8000 }], ceilW: 8000, readStep: 1, readNoise: 0, staleProb: 0, dips: [], replanMin: 10, paramVariant: "default" as const, params: {}, calm: true,
    hh: {
      demandKind: "holds" as const, solarKind: "below" as const, gridLimitW: limit, marginPct: 20, demandForecast: new Array(nSeg).fill(1000) as number[], demandFactor: new Array(nSeg).fill(0.9) as number[], spikes: [],
      solarForecast: new Array(nSeg).fill(fcst) as number[], solarFactor: new Array(nSeg).fill(trueFrac) as number[], solarConf: 0.9, noise: 0, demandStaleProb: 0, forecastPeakW: 1000, capLowW: limit - 1200,
    },
  };
  const tweak = (h: HouseholdInput) => ({ ...h, solarNowW: fcst, solarAgeMin: 0 });
  return { sc, tweak, limit };
};

test("[v3 G2b] closed loop: a cloud, or a solar forecast far too high, cannot push the import over the known limit; asking for the solar credit makes the same loop cross it", () => {
  let withCredit = 0;
  let runs = 0;
  let atRisk = 0;
  for (let v = 0; v < 27; v++) {
    const { sc, tweak, limit } = cloudScenario(v);
    const run = runHouseholdLoop(sc, planGentle, { tweak });
    runs++;
    assert.equal(run.overLimitMin, 0, "variant " + v + ": the setpoint plus the true demand stayed inside the limit of " + limit);
    assert.ok(run.maxImportW <= limit + 1e-6, "variant " + v + ": import " + run.maxImportW);
    assert.ok(run.ticks.every((tk) => tk.decision.setpointW === null || (tk.decision.headroomCapW as number) <= limit - 1000 * 1.2 + 1e-9), "the cap never counts the solar");
    if (run.ticks.some((tk) => tk.decision.status === "TARGET_AT_RISK" || tk.decision.status === "TARGET_UNREACHABLE")) atRisk++;
    // the same world with the credit switched ON shows what the default protects against
    const credited = runHouseholdLoop(sc, planGentle, { tweak, params: { solarCreditPct: 100 } });
    if (credited.overLimitMin > 0) withCredit++;
  }
  assert.ok(atRisk >= 20, "the shortfall is reported, not hidden: " + atRisk + " of " + runs + " runs flagged at risk or unreachable");
  assert.ok(withCredit >= 10, "the loop is able to expose the old behaviour: with solarCreditPct 100 the limit was crossed in " + withCredit + " of " + runs + " runs");
  console.log("[gentle G2] cloud scenarios: " + runs + " runs, solar not credited: limit never crossed; flagged at risk or unreachable in " + atRisk + "; with the credit switched on the limit was crossed in " + withCredit);
});

test("[v3 G5a] the setpoint basis is explicit and every grid-side limit is converted to it: the default UNSETTLED holds under either convention, GRID_AC keeps the exact grid-side arithmetic, battery-side ceilings are never raised", () => {
  assert.equal(DEFAULT_GENTLE_POLICY.setpointBasis, "UNSETTLED");
  assert.equal(DEFAULT_GENTLE_PARAMS.setpointConversionEff, 0.85);
  assert.equal(PARAM_PROVENANCE.setpointBasis?.kind, "PROVISIONAL");
  assert.equal(PARAM_PROVENANCE.setpointConversionEff?.kind, "PROVISIONAL");
  const H: HouseholdInput = { gridImportLimitW: 5000, demandProfile: flat(1000), demandProfileAgeMin: 0 };
  const run = (basis: string | undefined, over: Partial<GentleInput> = {}) => planGentle({ ...hbase, household: H, ...(basis === undefined ? {} : { policy: { setpointBasis: basis as GentlePolicy["setpointBasis"] } }), ...over });
  // 5000 - 1000 x 1.2 = 3800 grid-side watts; a setpoint that is battery-side watts can use 0.85 of that: 3230 -> 3200
  assert.equal(run("GRID_AC").headroomCapW, 3800);
  assert.equal(run("BATTERY_DC").headroomCapW, 3200);
  assert.equal(run("UNSETTLED").headroomCapW, 3200);
  assert.equal(run(undefined).headroomCapW, 3200, "the default is the unsettled basis");
  assert.equal(run(undefined).setpointBasis, "UNSETTLED");
  assert.equal(run("GRID_AC").setpointBasis, "GRID_AC");
  assert.equal(run("BATTERY_DC", { params: { setpointConversionEff: 0.9 } }).headroomCapW, 3400);
  assert.equal(run("BATTERY_DC", { params: { setpointConversionEff: 1 } }).headroomCapW, 3800);
  assert.equal(run("GRID_AC", { params: { setpointConversionEff: 0.5 } }).headroomCapW, 3800, "a settled grid-side basis needs no conversion");
  // whatever the basis, the recommended setpoint stays inside the cap and the import it draws stays inside the limit, on both readings
  for (const basis of ["GRID_AC", "BATTERY_DC", "UNSETTLED", undefined]) {
    const d = run(basis, { targetSocPct: 100, socPct: 30 });
    assert.ok((d.setpointW as number) <= (d.headroomCapW as number), String(basis));
    const importGrid = (d.setpointW as number) + 1200;
    const importBattery = (d.setpointW as number) / 0.85 + 1200;
    assert.ok((d.household?.projectedImportW as number) <= 5000 + 1e-6, "reported import " + d.household?.projectedImportW);
    assert.ok(basis === "GRID_AC" ? importGrid <= 5000 : importBattery <= 5000 + 1e-6, String(basis) + ": the draw at an efficiency of 0.85 stays inside the limit");
  }
  assert.equal(run("GRID_AC", { targetSocPct: 100, socPct: 30 }).household?.projectedImportW, 5000, "grid-side: import = setpoint + demand");
  assert.ok((run("UNSETTLED", { targetSocPct: 100, socPct: 30 }).household?.projectedImportW as number) < 5000 && (run("UNSETTLED", { targetSocPct: 100, socPct: 30 }).household?.projectedImportW as number) > 4900);
  // validated
  for (const setpointConversionEff of [0, -0.1, 1.01, NaN, Infinity]) assert.equal(plan({ params: { setpointConversionEff } }).status, "INVALID", String(setpointConversionEff));
  for (const setpointConversionEff of [0.01, 0.5, 1]) assert.equal(plan({ params: { setpointConversionEff } }).status, "OK", String(setpointConversionEff));
  for (const setpointBasis of ["AC", "", null, 7, "grid_ac"]) assert.equal(plan({ policy: { setpointBasis } as unknown as Partial<GentlePolicy> }).status, "INVALID", String(setpointBasis));
  // named ceilings: an unlabelled one is already in setpoint units; a battery-side one is never raised; a grid-side one is converted DOWN unless the basis is grid-side
  const CB = (c: NamedCeiling[], basis?: string) => plan({ ceilings: c, ...(basis === undefined ? {} : { policy: { setpointBasis: basis as GentlePolicy["setpointBasis"] } }) });
  const unl: NamedCeiling[] = [{ name: "owner_maximum", watts: 5000 }];
  const bat: NamedCeiling[] = [{ name: "battery_max_charge", watts: 5000, basis: "BATTERY_DC" }];
  const grid: NamedCeiling[] = [{ name: "grid_charge_power", watts: 5000, basis: "GRID_AC" }];
  for (const b of [undefined, "GRID_AC", "BATTERY_DC", "UNSETTLED"]) {
    assert.equal(CB(unl, b).ceilingW, 5000, "unlabelled, " + b);
    assert.equal(CB(bat, b).ceilingW, 5000, "battery-side, " + b);
  }
  assert.equal(CB(grid, "GRID_AC").ceilingW, 5000);
  assert.equal(CB(grid, "BATTERY_DC").ceilingW, 4200, "5000 x 0.85 = 4250, down to a step");
  assert.equal(CB(grid, "UNSETTLED").ceilingW, 4200);
  assert.equal(CB(grid, undefined).ceilingW, 4200);
  const mix = CB([...unl, { name: "grid_charge_power", watts: 5200, basis: "GRID_AC" }]);
  assert.equal(mix.ceilingW, 4400, "5200 x 0.85 = 4420 is the smallest");
  assert.equal(mix.ceilingName, "grid_charge_power");
  assert.ok((mix.setpointW as number) <= 4400);
  assert.equal(CB([{ name: "x", watts: 5000, basis: "weird" as unknown as "GRID_AC" }], "UNSETTLED").ceilingW, 4200, "an unrecognised label is treated as grid-side: the lower figure");
  assert.equal(CB([{ name: "x", watts: 5000, basis: "weird" as unknown as "GRID_AC" }], "GRID_AC").ceilingW, 5000);
  // the helpers, exported pure
  assert.equal(G4.setpointScale("GRID_AC", 0.85), 1);
  assert.equal(G4.setpointScale("BATTERY_DC", 0.85), 0.85);
  assert.equal(G4.setpointScale("UNSETTLED", 0.85), 0.85);
  assert.equal(G4.ceilingInSetpointUnits({ name: "a", watts: 1000, basis: "GRID_AC" }, "UNSETTLED", 0.8), 800);
  assert.equal(G4.ceilingInSetpointUnits({ name: "a", watts: 1000, basis: "BATTERY_DC" }, "UNSETTLED", 0.8), 1000);
  assert.equal(G4.ceilingInSetpointUnits({ name: "a", watts: 1000 }, "BATTERY_DC", 0.8), 1000);
  // the provisional parameters that shaped the answer are listed
  const listed = run(undefined).provisionalInUse.map((x) => x.name);
  assert.ok(listed.includes("setpointBasis") && listed.includes("setpointConversionEff"));
  assert.ok(!run("GRID_AC").provisionalInUse.some((x) => x.name === "setpointConversionEff"));
  // v1 numbers are untouched: no household and no labelled ceiling means no conversion at all
  assert.equal(plan().ceilingW, 5000);
});

test("[v3 G5b] closed loop with a simulator convention that DIFFERS from the model's: with the default basis the limit holds whether the actuator applies grid-side or battery-side watts; a model that assumed the grid side is exposed", () => {
  let n = 0;
  let reachedBattery = 0;
  let feasible = 0;
  const grid: Partial<GentlePolicy> = { setpointBasis: "GRID_AC" };
  for (let id = 0; id < 240; id++) {
    const sc = makeHouseholdScenario(id);
    if (sc.hh.demandKind === "exceeds") continue;   // demand above the forecast and its margin can cross any limit; that is reported elsewhere
    n++;
    const defGrid = runHouseholdLoop(sc, planGentle, { applyBasis: "GRID_AC" });
    const defBat = runHouseholdLoop(sc, planGentle, { applyBasis: "BATTERY_DC" });
    assert.equal(defGrid.overLimitMin, 0, "default basis, grid-side actuator, scenario " + id);
    assert.equal(defBat.overLimitMin, 0, "default basis, battery-side actuator, scenario " + id);
    assert.ok(defBat.maxImportW <= sc.hh.gridLimitW + 1e-6, "scenario " + id + " import " + defBat.maxImportW);
    // the same assumption meeting a grid-side actuator is exact
    assert.equal(runHouseholdLoop(sc, planGentle, { applyBasis: "GRID_AC", policy: grid }).overLimitMin, 0, "scenario " + id);
    if (sc.kind === "in-band" && feasibilityHH(sc) === "margin") {
      feasible++;
      if (defBat.reachedTolMin !== null && defBat.reachedTolMin <= defBat.deadlineMin) reachedBattery++;
    }
  }
  // The loop must be able to SEE a convention mismatch: demand at its forecast, no demand margin, the cap binding (an at-risk target). A model that
  // assumed grid-side watts, meeting a battery-side actuator, crosses the limit; the default basis does not, with either actuator.
  let exposed = 0;
  let minutes = 0;
  const tight: Partial<GentleParams> = { demandMarginPct: 0 };
  for (let v = 0; v < 27; v++) {
    const { sc } = cloudScenario(v);
    const wrong = runHouseholdLoop(sc, planGentle, { applyBasis: "BATTERY_DC", params: tight, policy: grid });
    if (wrong.overLimitMin > 0) { exposed++; minutes += wrong.overLimitMin; }
    assert.equal(runHouseholdLoop(sc, planGentle, { applyBasis: "BATTERY_DC", params: tight }).overLimitMin, 0, "default basis, battery-side actuator, variant " + v);
    assert.equal(runHouseholdLoop(sc, planGentle, { applyBasis: "GRID_AC", params: tight }).overLimitMin, 0, "default basis, grid-side actuator, variant " + v);
    assert.equal(runHouseholdLoop(sc, planGentle, { applyBasis: "GRID_AC", params: tight, policy: grid }).overLimitMin, 0, "grid-side assumption, grid-side actuator, variant " + v);
  }
  console.log("[gentle G5] " + n + " scenarios without demand above the forecast: the default basis crossed the limit in 0 runs with either actuator; tight cases (no margin, cap binding): a grid-side assumption under a battery-side actuator crossed it in " + exposed + " of 27 (" + minutes + " minutes with the setpoint above the limit), the default in 0; feasible-with-margin runs reaching the deadline with a battery-side actuator " + reachedBattery + " of " + feasible);
  assert.ok(n >= 120, "scenarios: " + n);
  assert.ok(exposed >= 15 && minutes > 1000, "the loop is able to expose a convention mismatch: " + exposed + " of 27, " + minutes + " minutes");
  assert.ok(feasible >= 50 && reachedBattery >= feasible - 2, "the conservative default still reaches the deadline where the true battery can: " + reachedBattery + " of " + feasible);
});

// ---- G6: taper shapes the model does not assume ------------------------------------------------------------------------------------------
type TaperMake = (sc: ReturnType<typeof makeScenario>) => TrueTaper;
const TAPERS: readonly [string, TaperMake][] = [
  ["LINEAR (the model's shape)", (sc) => sc.trueTaper],
  ["CV_TAIL, tau 3, floor 0.05", (sc) => ({ startSocPct: Math.max(sc.trueTaper.startSocPct, 90), endFraction: 0.05, shape: "CV_TAIL", tauPct: 3 })],
  ["CV_TAIL, tau 2, floor 0.03", (sc) => ({ startSocPct: Math.max(sc.trueTaper.startSocPct, 90), endFraction: 0.03, shape: "CV_TAIL", tauPct: 2 })],
  ["CURRENT_ABSOLUTE, 60 % of the ceiling", (sc) => ({ startSocPct: sc.trueTaper.startSocPct, endFraction: sc.trueTaper.endFraction, shape: "CURRENT_ABSOLUTE", ratedW: 0.6 * sc.ceilW })],
  ["CURRENT_ABSOLUTE, 85 % of the ceiling", (sc) => ({ startSocPct: sc.trueTaper.startSocPct, endFraction: sc.trueTaper.endFraction, shape: "CURRENT_ABSOLUTE", ratedW: 0.85 * sc.ceilW })],
];

test("[v3 G6a] the simulator's true taper has three shapes: the linear one the model assumes, a constant-voltage tail and a current-based limit independent of the ceiling", () => {
  const sc0 = { ...makeScenario(1), ceilW: 6000, nominalKwh: 30, trueCapacityKwh: 30, trueEff: 1, dips: [] as [] };
  const linear: TrueTaper = { startSocPct: 90, endFraction: 0.15 };
  const cv: TrueTaper = { startSocPct: 90, endFraction: 0.05, shape: "CV_TAIL", tauPct: 3 };
  const cur: TrueTaper = { startSocPct: 90, endFraction: 0.15, shape: "CURRENT_ABSOLUTE", ratedW: 4000 };
  const A = (t: TrueTaper, soc: number, ceilW = 6000) => acceptW({ ceilW, trueTaper: t }, soc);
  // the linear shape is exactly the original expression, and an explicit LINEAR label changes nothing
  for (const soc of [10, 90, 92, 95, 99, 100]) {
    assert.equal(A(linear, soc), 6000 * trueFraction(soc, linear));
    assert.equal(A({ ...linear, shape: "LINEAR" }, soc), A(linear, soc));
  }
  // CV tail: the full ceiling to the start, then exp(-(soc - start) / tau) down to the floor, never rising
  assert.equal(A(cv, 90), 6000);
  assert.ok(Math.abs(A(cv, 93) - 6000 * Math.exp(-1)) < 1e-9);
  assert.ok(Math.abs(A(cv, 96) - 6000 * Math.exp(-2)) < 1e-9);
  assert.equal(A(cv, 100), 6000 * 0.05, "the floor");
  for (let soc = 80; soc < 100; soc += 0.5) assert.ok(A(cv, soc + 0.5) <= A(cv, soc) + 1e-9, "never rising at " + soc);
  assert.ok(A(cv, 95) < A(linear, 95) / 3, "far harsher than the linear shape at 95 %: " + A(cv, 95) + " vs " + A(linear, 95));
  // current-based: its own limit, independent of the ceiling the model knows, linear above the start
  assert.equal(A(cur, 50), 4000);
  assert.equal(A(cur, 50, 8000), 4000, "the ceiling is irrelevant");
  assert.equal(A(cur, 50, 3000), 4000, "and it may exceed it: the delivered power is then the setpoint's, which the loop caps by the ceiling");
  assert.ok(Math.abs(A(cur, 95) - 4000 * trueFraction(95, cur)) < 1e-9);
  // the shapes change the time the TRUE battery needs (the closed loop would be blind if they did not)
  const base = { ...sc0, startSocPct: 80, targetSocPct: 100, dips: [] as [] };
  const tL = trueFinishMin({ ...base, trueTaper: linear }, 6000) as number;
  const tC = trueFinishMin({ ...base, trueTaper: cv }, 6000) as number;
  const tR = trueFinishMin({ ...base, trueTaper: cur }, 6000) as number;
  assert.ok(tC > tL + 20, "a CV tail takes much longer to 100 %: " + tC + " vs " + tL);
  assert.ok(tR > tL + 15, "a lower current-based limit takes longer: " + tR + " vs " + tL);
  // the feasibility class follows the true shape
  const sc1 = { ...makeScenario(2), targetSocPct: 100, startSocPct: 50, bufferMin: 30, dips: [] as [] };
  assert.ok(["margin", "tight", "buffer", "infeasible"].includes(feasibility({ ...sc1, trueTaper: cv })));
});

test("[v3 G6b] closed loop under taper shapes the model does NOT assume: the misses are counted and printed, a 100 % target that misses was flagged at risk before the deadline, and what this shows and does not show is stated", () => {
  const rows: string[] = [];
  const stat = { margin: 0, reached: 0, miss: 0, flagged: 0, miss100: 0, flagged100: 0, margin100: 0, linearMiss: 0 };
  const unflagged: string[] = [];
  for (const [name, mk] of TAPERS) {
    let n = 0, margin = 0, reached = 0, miss = 0, flagged = 0, margin100 = 0, miss100 = 0, flagged100 = 0;
    for (let id = 0; id < 400; id++) {
      const sc0 = makeScenario(id);
      if (sc0.kind !== "in-band") continue;
      const sc = { ...sc0, trueTaper: mk(sc0) };
      n++;
      if (feasibility(sc) !== "margin") continue;   // what the TRUE battery, with ITS shape, can do at the full ceiling with time to spare
      margin++;
      const is100 = sc.targetSocPct >= 100;
      if (is100) margin100++;
      const run = runClosedLoop(sc);
      for (const tk of run.ticks) { assert.equal(tk.decision.guarantee, "NONE"); assert.equal(tk.decision.targetSocPct, sc.targetSocPct); assert.equal(tk.decision.actuationSupported, false); }
      if (run.reachedTolMin !== null && run.reachedTolMin <= run.deadlineMin) { reached++; continue; }
      miss++;
      if (is100) miss100++;
      const early = run.ticks.some((tk) => tk.t <= run.deadlineMin && (tk.decision.status === "TARGET_AT_RISK" || tk.decision.status === "TARGET_UNREACHABLE"));
      if (early) { flagged++; if (is100) flagged100++; } else unflagged.push(name + " scenario " + id + " target " + sc.targetSocPct);
      // A miss with a buffer of 0 has no tick after the deadline (it is the window end), so a miss that was not flagged before it is NOT claimed away: it is listed below.
    }
    rows.push(name.padEnd(40) + " in-band " + n + ", true battery feasible with margin " + margin + ": reached by the deadline " + reached + ", MISSED " + miss + " (flagged at risk before the deadline " + flagged + "); 100 % targets: " + margin100 + " feasible, missed " + miss100 + ", flagged " + flagged100);
    if (name.startsWith("LINEAR")) { stat.linearMiss = miss; assert.equal(miss, 0, "the model's own shape: every feasible-with-margin run reaches the target by the deadline (the existing claim)"); }
    else { stat.margin += margin; stat.reached += reached; stat.miss += miss; stat.flagged += flagged; stat.miss100 += miss100; stat.flagged100 += flagged100; stat.margin100 += margin100; }
  }
  for (const r of rows) console.log("[gentle taper] " + r);
  console.log("[gentle taper] shapes the model does not assume: " + stat.margin + " feasible-with-margin runs, " + stat.miss + " missed the deadline (" + (100 * stat.miss / stat.margin).toFixed(1) + " %), " + stat.flagged + " of them flagged at risk before the deadline; 100 % targets: " + stat.miss100 + " missed, " + stat.flagged100 + " flagged; not flagged before the deadline: " + (unflagged.length === 0 ? "none" : unflagged.join("; ")));
  // the closed loop must be CAPABLE of exposing a wrong taper assumption: misses exist, and they are mostly 100 % targets
  assert.ok(stat.miss >= 20, "the shapes expose misses: " + stat.miss);
  assert.ok(stat.miss100 >= 20 && stat.miss100 >= 0.7 * stat.miss, "a harsh taper hits the 100 % targets: " + stat.miss100 + " of " + stat.miss);
  // and the honest report the owner asked for: a 100 % target that is missed under a harsh taper was flagged TARGET_AT_RISK or TARGET_UNREACHABLE before the deadline
  assert.equal(stat.flagged100, stat.miss100, "every missed 100 % target was flagged at risk before the deadline");
  assert.ok(unflagged.length <= 0.1 * stat.miss, "a miss that was not flagged before the deadline is rare and printed: " + unflagged.join("; "));
  // the claim that is NOT made here: that the assumed taper is right (it is unmeasured), or that these shapes resemble the real BMS
  assert.match(NO_GUARANTEE_NOTE, /assumed/i);
});

// ---- G7: the minors ----------------------------------------------------------------------------------------------------------------------

test("[v3 G7 m1] a finish that lands after a FRACTIONAL horizon is late, never on time", () => {
  const m: ChargeModel = { capacityKwh: 30, chargeEff: 0.95, ceilingW: 8000, taperStartSocPct: 90, taperEndFraction: 0.15 };
  // 7600 W gives about 0.401 points a minute: from 79.5 to 80 takes 1.2465 minutes
  const full = projectCharge(79.5, 7600, 80, m, 5).finishMin as number;
  assert.ok(Math.abs(full - 1.2465) < 0.002, "closed form: " + full);
  assert.equal(projectCharge(79.5, 7600, 80, m, 1.2).finishMin, null, "1.2465 min is after a horizon of 1.2 min (it used to count as on time)");
  assert.equal(projectCharge(79.5, 7600, 80, m, 1.2464).finishMin, null);
  assert.ok(projectCharge(79.5, 7600, 80, m, 1.3).finishMin !== null);
  assert.equal(projectCharge(79.5, 7600, 80, m, 2).finishMin, full, "a whole-minute horizon is unchanged");
  assert.equal(projectCharge(79.5, 7600, 80, m, 1).finishMin, null);
  // through the controller: a fractional elapsed time never lets a late step through as the lowest step, and an at-risk reason is never the budget's when nothing is held
  let checked = 0;
  for (let k = 0; k < 900; k++) {
    const elapsed = 20 + k * 0.31;
    const socPct = 25 + (k % 37) * 0.7;
    const d = plan({ elapsedMin: elapsed, socPct, targetSocPct: 90, bufferMin: 60 });
    if (d.status === "NO_DATA" || d.status === "NOTHING_TO_CHARGE" || d.status === "DEADLINE_PASSED") continue;
    checked++;
    if (d.neededW !== null) {
      assert.equal(d.change, "START");
      assert.equal(d.status, "OK", "elapsed " + elapsed + " soc " + socPct + ": the lowest step makes the deadline, nothing is held: " + d.reasons.join(" | "));
      assert.ok((d.marginMin as number) >= -0.11, "margin " + d.marginMin + " at elapsed " + elapsed);
    }
  }
  assert.ok(checked > 400, "checked " + checked);
});

test("[v3 G7 m2] a fallback never holds anything after the window ends, and says so when it holds a rate inside the buffer", () => {
  for (const policy of ["KEEP_CURRENT", "USE_STATIC_PLAN"] as const) {
    for (const elapsedMin of [360, 361, 400]) {
      const d = plan({ socAgeMin: 99, elapsedMin, currentSetpointW: 3000, staticPlanRateW: 4000, policy: { fallbackPolicy: policy } });
      assert.equal(d.status, "NO_DATA");
      assert.equal(d.fallback.applied, true);
      assert.equal(d.fallback.setpointW, null, policy + " at " + elapsedMin + ": the window is over");
      assert.match(d.fallback.reason, /window has ended/);
    }
    // a household input that cannot be checked after the window end: the same
    const hh = hplan({ gridImportLimitW: 7000, demandProfile: flat(500), gridImportLimitAgeMin: 999 }, { elapsedMin: 370, currentSetpointW: 3000, staticPlanRateW: 4000, policy: { fallbackPolicy: policy } });
    assert.equal(hh.fallback.setpointW, null);
    // an unknown ceiling: still no recommendation (as before)
    assert.equal(plan({ ceilings: [], elapsedMin: 100, currentSetpointW: 3000, policy: { fallbackPolicy: policy } }).fallback.setpointW, null);
  }
  // inside the finish-early buffer (the deadline is minute 300, the window ends at 360): the hold stands, labelled
  const buf = plan({ socAgeMin: 99, elapsedMin: 310, currentSetpointW: 3000 });
  assert.equal(buf.fallback.setpointW, 3000);
  assert.match(buf.fallback.reason, /finish-early deadline has passed/);
  assert.match(buf.fallback.reason, /does not plan for the deadline/);
  const st = plan({ socAgeMin: 99, elapsedMin: 310, staticPlanRateW: 4000, policy: { fallbackPolicy: "USE_STATIC_PLAN" } });
  assert.equal(st.fallback.setpointW, 4000);
  assert.match(st.fallback.reason, /finish-early deadline has passed/);
  // before the deadline: no such note, and the answer is the old one
  const before = plan({ socAgeMin: 99, elapsedMin: 100, currentSetpointW: 3000 });
  assert.equal(before.fallback.setpointW, 3000);
  assert.doesNotMatch(before.fallback.reason, /deadline has passed/);
  assert.equal(plan({ socAgeMin: 99, elapsedMin: 299, currentSetpointW: 3000 }).fallback.setpointW, 3000);
  assert.equal(plan({ socAgeMin: 99, elapsedMin: 299.5, currentSetpointW: 3000 }).fallback.setpointW, 3000);
});

test("[v3 G7 m3] every recommended write is counted (the START and a safety decrease included) and none is ever blocked; a slew step smaller than the hysteresis is refused", () => {
  const start = plan({ changesUsed: 6, totalChangesUsed: 9 });
  assert.equal(start.change, "START");
  assert.equal(start.changesUsed, 6, "the START is free in the ordinary budget (v1)");
  assert.equal(start.totalChangesUsed, 10, "but it is a write: it counts in the total");
  assert.equal(plan({ changesUsed: 2 }).totalChangesUsed, 3, "missing total = the ordinary count, plus this write");
  const safety = plan({ currentSetpointW: 4800, lastChangeElapsedMin: 0, elapsedMin: 1, changesUsed: 6, totalChangesUsed: 12, ceilings: [{ name: "battery_max_charge", watts: 4000 }] });
  assert.equal(safety.change, "DECREASE");
  assert.ok((safety.setpointW as number) <= 4000, "a safety decrease is never blocked by a spent budget");
  assert.equal(safety.changesUsed, 6);
  assert.equal(safety.totalChangesUsed, 13, "but it is counted");
  const inc = plan({ currentSetpointW: 3000, socPct: 35, elapsedMin: 100, changesUsed: 2, totalChangesUsed: 5, lastChangeElapsedMin: 0 });
  assert.equal(inc.change, "INCREASE");
  assert.equal(inc.changesUsed, 3);
  assert.equal(inc.totalChangesUsed, 6);
  const held = plan({ currentSetpointW: 3000, socPct: 35, elapsedMin: 100, changesUsed: 6, totalChangesUsed: 8, lastChangeElapsedMin: 0 });
  assert.equal(held.change, "NONE");
  assert.equal(held.totalChangesUsed, 8, "no write, no count");
  for (const bad of [{ changesUsed: 3, totalChangesUsed: 2 }, { totalChangesUsed: 1.5 }, { totalChangesUsed: -1 }, { totalChangesUsed: NaN }] as Partial<GentleInput>[]) assert.equal(plan(bad).status, "INVALID", JSON.stringify(bad));
  assert.equal(plan({ targetSocPct: 9, changesUsed: 3 }).totalChangesUsed, 3);
  // the slew: a step smaller than the hysteresis could never save the hysteresis
  for (const params of [{ maxDecreaseStepW: 100 }, { maxDecreaseStepW: 400, hysteresisW: 500 }, { maxDecreaseStepW: 900, hysteresisW: 1000 }]) assert.equal(plan({ params }).status, "INVALID", JSON.stringify(params));
  assert.match(plan({ params: { maxDecreaseStepW: 100 } }).reasons.join(" "), /maxDecreaseStepW must be at least hysteresisW/);
  for (const params of [{ maxDecreaseStepW: 500, hysteresisW: 500 }, { maxDecreaseStepW: 1000 }, { maxDecreaseStepW: 100, hysteresisW: 0 }, { hysteresisW: 9000 }]) assert.equal(plan({ params }).status, "OK", JSON.stringify(params));
});

test("[v3 G7 m4] a setpoint in force with nothing (more) to charge or the window over is a STOP, told apart from no data; nothing else changes", () => {
  const done = plan({ socPct: 85, targetSocPct: 80, currentSetpointW: 4000 });
  assert.equal(done.status, "NOTHING_TO_CHARGE");
  assert.equal(done.stopRecommended, true);
  assert.equal(done.setpointW, null);
  assert.equal(done.change, "NONE", "the v1 fields are untouched");
  assert.equal(done.changeRecommended, false);
  assert.equal(plan({ socPct: 85, targetSocPct: 80, currentSetpointW: null }).stopRecommended, false);
  assert.equal(plan({ socPct: 85, targetSocPct: 80, currentSetpointW: 0 }).stopRecommended, false);
  const over = plan({ elapsedMin: 400, currentSetpointW: 3000 });
  assert.equal(over.status, "DEADLINE_PASSED");
  assert.equal(over.stopRecommended, true);
  assert.equal(plan({ elapsedMin: 400, currentSetpointW: null }).stopRecommended, false);
  // no data is not a stop, and the buffer is not a stop (the ceiling is the best effort there)
  assert.equal(plan({ socPct: null, currentSetpointW: 3000 }).stopRecommended, false);
  assert.equal(plan({ elapsedMin: 310, currentSetpointW: 3000 }).stopRecommended, false);
  assert.equal(plan({ currentSetpointW: 3000, elapsedMin: 100, socPct: 45 }).stopRecommended, false);
  assert.equal(plan().stopRecommended, false);
});

test("[v3 G7 m5] a hold that waits out the dwell projects the raise the model will actually make (the lowest step), not a raise to the ceiling", () => {
  const G: HouseholdInput = { gridImportLimitW: 30000, demandProfile: flat(500) };
  const st = (soc: number, since: number) => hplan(G, { currentSetpointW: 3000, lastChangeElapsedMin: 60 - since, elapsedMin: 60, socPct: soc });
  let waits = 0;
  for (const soc of [32, 33, 34, 35, 36, 37]) {
    const d = st(soc, 5);
    if (!d.codes.includes("HELD_DWELL")) continue;
    waits++;
    assert.ok((d.marginMin as number) >= -0.11, "soc " + soc + ": " + d.marginMin);
    assert.ok((d.marginMin as number) < 10, "soc " + soc + ": the margin of a raise to the ceiling would be 15 min or more, this is the lowest step's: " + d.marginMin);
    assert.equal(d.status, "OK");
  }
  assert.ok(waits >= 3, "waits exercised: " + waits);
});

test("[v3 G7 m6] a second SOC reading must be consistent with the first: not far below it, not further above it than a charge could carry it; a clock that went backwards is INVALID", () => {
  const PS = (soc: number, prev: { socPct: number; elapsedMin: number } | null | undefined, over: Partial<GentleInput> = {}) => plan({ socPct: soc, previousSoc: prev, elapsedMin: 100, currentSetpointW: 3000, lastChangeElapsedMin: 50, ...over });
  const prev = { socPct: 40, elapsedMin: 90 };
  assert.equal(PS(41, prev).status, "OK");
  assert.equal(PS(37, prev).status, "OK", "exactly the regression tolerance of 3 points is plausible");
  const down = PS(36.9, prev);
  assert.equal(down.status, "NO_DATA");
  assert.ok(down.codes.includes("SOC_IMPLAUSIBLE"));
  assert.equal(down.setpointW, null);
  assert.equal(down.fallback.applied, true);
  assert.match(down.reasons.join(" "), /below the previous one/);
  // 10 minutes at up to 60 points an hour is 10 points, plus the 1 point resolution and the 3 point tolerance: 14
  assert.equal(PS(54, prev).status, "OK");
  const up = PS(54.5, prev);
  assert.equal(up.status, "NO_DATA");
  assert.ok(up.codes.includes("SOC_IMPLAUSIBLE"));
  assert.match(up.reasons.join(" "), /could carry it/);
  assert.equal(PS(44, { socPct: 40, elapsedMin: 100 }).status, "OK", "the same minute: the resolution and the tolerance only");
  assert.equal(PS(44.5, { socPct: 40, elapsedMin: 100 }).status, "NO_DATA");
  assert.equal(PS(60, { socPct: 40, elapsedMin: 40 }).status, "OK", "60 minutes later 20 points is within 60 points an hour");
  // no previous reading: no check; a stale or unknown current reading is the old NO_DATA with its own code
  assert.equal(PS(60, null).status, "OK");
  assert.equal(PS(60, undefined).status, "OK");
  assert.ok(PS(20, null, { socAgeMin: 99 }).codes.includes("STALE_SOC"));
  // a bad second reading or a clock that went backwards is INVALID, never guessed around
  for (const bad of [{ socPct: 40, elapsedMin: 150 }, { socPct: 140, elapsedMin: 90 }, { socPct: NaN, elapsedMin: 90 }, { socPct: 40, elapsedMin: -1 }, "x", { socPct: 40 }] as unknown[]) assert.equal(PS(41, bad as { socPct: number; elapsedMin: number }).status, "INVALID", JSON.stringify(bad));
  for (const params of [{ socRegressionTolPct: -1 }, { socRegressionTolPct: 51 }, { socJumpPctPerHour: 0 }, { socJumpPctPerHour: 1001 }, { socJumpPctPerHour: NaN }]) assert.equal(plan({ params }).status, "INVALID", JSON.stringify(params));
  assert.equal(DEFAULT_GENTLE_PARAMS.socRegressionTolPct, 3);
  assert.equal(DEFAULT_GENTLE_PARAMS.socJumpPctPerHour, 60);
  assert.equal(PS(50, prev, { params: { socJumpPctPerHour: 30 } }).status, "NO_DATA", "the rate is a parameter: 5 + 1 + 3 = 9 points allowed, 10 are not");
  assert.equal(PS(50, prev, { params: { socJumpPctPerHour: 40 } }).status, "OK", "6.7 + 1 + 3 = 10.7 points allowed");
});

test("[v3 G7 m7] a window that starts exactly at the clock change, or inside the hour a spring change skips, has an ambiguous real length: unknown, nothing is recommended", () => {
  const T = TIME as unknown as { ambiguousClockStart: (startMin: number, day: ClockDay) => boolean };
  // spring forward (the hour 120-179 does not exist), autumn back (the change minute is ambiguous), an ordinary day
  for (const start of [120, 121, 150, 179]) assert.equal(T.ambiguousClockStart(start, SPRING), true, "spring " + start);
  for (const start of [119, 180, 0, 22 * 60]) assert.equal(T.ambiguousClockStart(start, SPRING), false, "spring " + start);
  assert.equal(T.ambiguousClockStart(120, AUTUMN), true);
  for (const start of [60, 90, 119, 121, 0, 22 * 60]) assert.equal(T.ambiguousClockStart(start, AUTUMN), false, "autumn " + start + " (the repeated hour is read as the first pass: an open ruling)");
  for (const start of [0, 120, 150, 1439]) assert.equal(T.ambiguousClockStart(start, ORDINARY), false);
  assert.equal(T.ambiguousClockStart(NaN, SPRING), false);
  // the window length is unknown for such a start, and an ordinary start is unchanged
  assert.equal(windowRealMinutes(120, 4 * 60, SPRING), null);
  assert.equal(windowRealMinutes(150, 4 * 60, SPRING), null);
  assert.equal(windowRealMinutes(120, 4 * 60, AUTUMN), null);
  assert.equal(windowRealMinutes(22 * 60, 4 * 60, SPRING), 300);
  assert.equal(windowRealMinutes(22 * 60, 4 * 60, AUTUMN), 420);
  assert.equal(windowRealMinutes(60, 4 * 60, AUTUMN), 180 + 60, "inside the repeated hour: read as the first pass, so the repeat is counted");
  for (const [start, day] of [[120, SPRING], [150, SPRING], [179, SPRING], [120, AUTUMN]] as [number, ClockDay][]) {
    const d = plan({ chargeWindow: { startMin: start, endMin: 6 * 60, clockDay: day }, currentSetpointW: 3000 });
    assert.equal(d.status, "INVALID", start + " " + day.deltaMin);
    assert.equal(d.setpointW, null);
    assert.equal(d.changeRecommended, false);
    assert.match(d.reasons.join(" "), /ambiguous/);
    assert.equal(d.fallback.applied, false, "an invalid input has no fallback");
  }
  assert.equal(plan({ chargeWindow: { startMin: 22 * 60, endMin: 6 * 60, clockDay: SPRING } }).status, "OK");
  assert.equal(plan({ chargeWindow: { startMin: 60, endMin: 6 * 60, clockDay: AUTUMN } }).status, "OK");
  assert.equal(plan({ chargeWindow: { startMin: 119, endMin: 9 * 60, clockDay: SPRING } }).status, "OK");
});

test("[v3 G7 m8] the wording claims no more than the model can know: the note does not say 100 percent cannot be reached, the header scopes 'safe limit' to the model's estimate, the README says what is not observed", () => {
  assert.doesNotMatch(NO_GUARANTEE_NOTE, /cannot be reached/);
  assert.match(NO_GUARANTEE_NOTE, /NOT guaranteed/);
  assert.match(NO_GUARANTEE_NOTE, /100 percent/);
  assert.match(NO_GUARANTEE_NOTE, /not measured/);
  assert.match(NO_GUARANTEE_NOTE, /fixed rate/);
  assert.match(NO_GUARANTEE_NOTE, /taper/);
  assert.match(NO_GUARANTEE_NOTE, /read-only/);
  const raw = readFileSync(new URL("../src/gentleController.ts", import.meta.url), "utf8");
  assert.doesNotMatch(raw, /never exceeds a safe limit/);
  assert.match(raw, /as its inputs and assumptions state it/);
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  assert.doesNotMatch(readme, /follows the real taper/);
  assert.match(readme, /does not know the real taper or capacity/);
  assert.doesNotMatch(readme, /cannot be reached at a fixed rate because the BMS tapers/);
  assert.match(readme, /held back by the changes budget/, "the at-risk case held by the budget is listed with the statuses");
  assert.match(readme, /model estimate/i);
  for (const d of [plan(), plan({ socPct: null }), plan({ targetSocPct: 100, socPct: 40 })]) assert.equal(d.guaranteeNote, NO_GUARANTEE_NOTE);
});

test("[v3 G7 m9] a power ceiling taken from a current limit uses the lowest plausible voltage, and the amps the actuator would set never exceed the limit at any voltage", () => {
  assert.equal(powerFromCurrent(60, 51.2), 3072, "no minimum voltage: unchanged");
  assert.equal(powerFromCurrent(60, 56, 48), 2880, "the lower of the two voltages");
  assert.equal(powerFromCurrent(60, 44, 48), 2640);
  assert.equal(powerFromCurrent(60, 51.2, null), 3072);
  for (const bad of [0, -1, NaN, Infinity]) assert.equal(powerFromCurrent(60, 51.2, bad), null, "a minimum voltage that is not a positive number is unknown: " + bad);
  assert.equal(powerFromCurrent(null, 51.2, 48), null);
  // at the high voltage the ceiling asks for more amps than the limit allows at a lower one: capped
  const hi = powerFromCurrent(60, 58) as number;
  assert.equal(hi, 3480);
  assert.ok(hi / 44 > 60, "the power from a high voltage would be " + (hi / 44).toFixed(1) + " A at 44 V");
  assert.equal(G4.ampsFromPower(hi, 44, 60), 60);
  assert.ok(Math.abs((G4.ampsFromPower(2640, 51.2, 60) as number) - 2640 / 51.2) < 1e-12);
  assert.equal(G4.ampsFromPower(3000, 50, 60), 60);
  assert.equal(G4.ampsFromPower(0, 50, 60), 0);
  for (const bad of [[null, 50, 60], [3000, 0, 60], [3000, 50, -1], [3000, NaN, 60], [-5, 50, 60], [3000, 50, null]] as [unknown, unknown, unknown][]) assert.equal(G4.ampsFromPower(bad[0] as number, bad[1] as number, bad[2] as number), null, JSON.stringify(bad));
});
