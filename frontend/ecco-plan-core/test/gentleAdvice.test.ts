import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { adviseGentleRate, adviceFromDecision, ADVICE_REASONS } from "../src/gentleAdvice.ts";
import type { AdviceReason, GentleAdvice, GentleAdviceInput } from "../src/gentleAdvice.ts";
import * as ADVICE_MODULE from "../src/gentleAdvice.ts";
import { planGentle, projectCharge, windowRealMinutes, CONTROLLER_LABEL, DEFAULT_GENTLE_PARAMS, GENTLE_RECOMMENDED_PARAMS, ACTUATION_REASON } from "../src/gentleController.ts";
import type { GentleDecision, GentleInput, NamedCeiling } from "../src/gentleController.ts";
import type { ClockDay } from "../src/time.ts";
import { rng } from "./fixtures.ts";

// The stateless gentle RATE ADVICE (src/gentleAdvice.ts): the gentlest rate that still reaches the target by the deadline, one reason code per
// decision, no advice (and the reason) on missing or stale data, hard limits, monotone, and no path that could change anything.
// Fictional illustrative values only (no site data).

const ORDINARY: ClockDay = { changeAtMin: 0, deltaMin: 0 };
const CEILINGS: NamedCeiling[] = [
  { name: "owner_maximum", watts: 5000 },
  { name: "battery_max_charge", watts: 6200 },
  { name: "grid_charge_current", watts: null },
];
const base: GentleAdviceInput = {
  targetSocPct: 80, bufferMin: 60, chargeWindow: { startMin: 22 * 60, endMin: 4 * 60, clockDay: ORDINARY }, elapsedMin: 0, socPct: 20, socAgeMin: 1,
  capacityKwh: 30, capacityUpPct: 6, ceilings: CEILINGS,
};
const advise = (over: Partial<GentleAdviceInput> = {}): GentleAdvice => adviseGentleRate({ ...base, ...over });
const P = DEFAULT_GENTLE_PARAMS;
const STEP = P.stepW;

/** A deep freeze, so that any write to the input throws (the tests run in strict mode). */
function deepFreeze<T>(x: T): T {
  if (x !== null && typeof x === "object" && !Object.isFrozen(x)) {
    Object.freeze(x);
    for (const v of Object.values(x as Record<string, unknown>)) deepFreeze(v);
  }
  return x;
}

// ---- the label, the shape, the honest "not supported" ----------------------------------------------------------------------------------

test("advice is labelled 'model, not a command', never claims actuation and never guarantees the target", () => {
  const a = advise();
  assert.equal(a.label, CONTROLLER_LABEL);
  assert.equal(a.label, "model, not a command");
  assert.equal(a.actuationSupported, false);
  assert.equal(a.actuationReason, ACTUATION_REASON);
  assert.equal(a.guarantee, "NONE");
  assert.match(a.guaranteeNote, /NOT guaranteed/);
  for (const over of [{ socPct: null }, { socPct: 99 }, { ceilings: [] }, { targetSocPct: 3 }] as Partial<GentleAdviceInput>[]) {
    const b = advise(over);
    assert.equal(b.actuationSupported, false);
    assert.equal(b.guarantee, "NONE");
    assert.equal(b.label, CONTROLLER_LABEL);
  }
});

test("static: the module has no service call, write, network, file, clock or randomness, imports only the model, and is not re-exported by the package index", () => {
  const raw = readFileSync(new URL("../src/gentleAdvice.ts", import.meta.url), "utf8");
  const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'])\/\/.*$/gm, "$1").replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
  for (const banned of [/callService/, /callWS/, /\bhass\b/i, /\bfetch\s*\(/, /XMLHttpRequest|WebSocket|EventSource|sendBeacon/, /\bDate\b/, /Math\.random/, /performance\.now/, /setTimeout|setInterval/,
    /\bwrite/i, /turn_on|set_value|press|modbus|register/i, /\bimport\s*\(/, /\bclass\s/, /\basync\b|\bawait\b|\bPromise\b/, /\bprocess\b/, /\bwindow\b|\bdocument\b|\bglobalThis\b/,
    /localStorage|sessionStorage|indexedDB/, /\bthis\b/, /\bnew\s+(Date|Function|Worker)/, /\beval\b/, /require\s*\(/, /\bconsole\./, /node:/, /readFile|writeFile|createWriteStream|\bfs\b/, /\.(set|delete|clear)\s*\(/]) {
    assert.doesNotMatch(code, banned, "matches " + banned);
  }
  assert.deepEqual([...raw.matchAll(/^import\s+(?:type\s+)?\{[^}]*\}\s*from\s+"([^"]+)"/gm)].map((m) => m[1]).sort(), ["./gentleController.ts", "./gentleController.ts"]);
  assert.doesNotMatch(raw, /actuationSupported:\s*true/);
  assert.equal((raw.match(/actuationSupported:\s*false/g) ?? []).length, 2, "the type and the one place it is set, both false");
  for (const name of Object.keys(ADVICE_MODULE)) assert.doesNotMatch(name, /^(write|send|call|post|put|set[A-Z]|execute|dispatch|publish|save|push|apply|actuate)/, "export " + name + " sounds like a write");
  // The Energy Actions card bundle is declared by a pin-chain entry (epc4) and any module the package index exports changes it (measured): re-export this one only
  // together with a new chain entry.
  const index = readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
  assert.doesNotMatch(index, /gentleAdvice/, "re-exporting the advice from the package index changes the pinned card bundle; add a chain entry first");
});

// ---- the gentlest rate -----------------------------------------------------------------------------------------------------------------

test("the advised rate is the lowest 100 W step that reaches the target by the deadline (hand-checked, and it equals the model's stateless answer)", () => {
  const a = advise();
  // (80 - 19.5) % of 31.8 kWh = 19.239 kWh, / 0.95 = 20.252 kWh grid side, over 300 min = 4050 W -> 4100 W (the model's own hand-check).
  assert.equal(a.advice, "RATE");
  assert.equal(a.reason, "RATE_GENTLEST");
  assert.equal(a.outcome, "ON_TIME");
  assert.equal(a.targetWillBeMissed, false);
  assert.equal(a.status, "OK");
  assert.equal(a.degraded, false);
  assert.equal(a.neededW, 4100);
  assert.equal(a.rateW, 4100);
  assert.equal(a.minRateW, 500);
  assert.equal(a.safeMaxW, 5000);
  assert.equal(a.limitedBy, "CEILING");
  assert.ok((a.marginMin as number) >= 0);
  assert.match(a.summary, /^Charge at 4100 W: the lowest rate that reaches 80 % by the deadline/);
  const m = planGentle({ ...base, currentSetpointW: null, lastChangeElapsedMin: null, changesUsed: 0 } as GentleInput);
  assert.equal(m.setpointW, a.rateW);
  assert.equal(m.neededW, a.neededW);
  assert.equal(m.status, a.status);
  assert.deepEqual(m.codes, a.codes);
});

test("a linear search agrees: the advised rate reaches the target by the deadline and one step lower does not (random states)", () => {
  const r = rng(20261121);
  let checked = 0;
  for (let n = 0; n < 2000; n++) {
    const input = randomInput(r);
    if (input.household !== undefined) continue;   // the projection below has no grid headroom term
    const a = adviseGentleRate(input);
    if (a.advice !== "RATE") continue;
    const d = a.decision;
    const p = { ...P, ...(input.params ?? {}) };
    const real = windowRealMinutes(input.chargeWindow.startMin, input.chargeWindow.endMin, input.chargeWindow.clockDay) as number;
    const hold = input.targetSocPct >= 100 ? p.topHoldMin : 0;
    const avail = real - input.bufferMin - input.elapsedMin - hold;
    const model = {
      capacityKwh: Math.max(input.capacityKwh, input.learnedCapacityKwh ?? 0) * (1 + input.capacityUpPct / 100), chargeEff: p.chargeEff, ceilingW: d.ceilingW as number,
      taperStartSocPct: p.taperStartSocPct, taperEndFraction: p.taperEndFraction,
    };
    const planSoc = Math.max(0, (input.socPct as number) - p.socResolutionPct / 2);
    const reaches = (w: number) => projectCharge(planSoc, w, input.targetSocPct, model, avail).finishMin !== null;
    assert.ok(reaches(a.rateW as number), "the advised rate makes the deadline: " + JSON.stringify(input));
    if ((a.rateW as number) - STEP >= a.minRateW) assert.ok(!reaches((a.rateW as number) - STEP), "one step lower would miss: " + JSON.stringify(input));
    assert.equal(a.rateW, a.neededW, "a RATE is exactly what is needed, never more");
    checked++;
  }
  assert.ok(checked > 100, "enough RATE cases were checked: " + checked);
});

test("the practical minimum: a target that needs almost nothing still gets the minimum, said so, and never a lower rate", () => {
  const a = advise({ socPct: 79, targetSocPct: 80, chargeWindow: { startMin: 0, endMin: 8 * 60, clockDay: ORDINARY } });
  assert.equal(a.advice, "RATE");
  assert.equal(a.reason, "RATE_AT_PRACTICAL_MINIMUM");
  assert.equal(a.rateW, a.minRateW);
  assert.equal(a.rateW, 500);
  assert.equal(a.outcome, "ON_TIME");
  assert.match(a.summary, /practical minimum/);
  assert.ok((a.marginMin as number) > 60, "the target is reached long before the deadline");
  // a larger minimum raises the floor (rounded up to a step) and the advice never goes below it
  const b = advise({ socPct: 79, targetSocPct: 80, chargeWindow: { startMin: 0, endMin: 8 * 60, clockDay: ORDINARY }, params: { minW: 650 } });
  assert.equal(b.minRateW, 700);
  assert.equal(b.rateW, 700);
});

test("when nothing gentler reaches the target the rate is the highest safe one, and it says so", () => {
  // 20 % -> 80 % of 31.8 kWh in a 6 h window with 60 min buffer needs 4100 W; with a 4100 W ceiling the rate IS the ceiling
  const a = advise({ ceilings: [{ name: "owner_maximum", watts: 4100 }] });
  assert.equal(a.advice, "RATE");
  assert.equal(a.reason, "RATE_AT_SAFE_MAXIMUM");
  assert.equal(a.rateW, 4100);
  assert.equal(a.safeMaxW, 4100);
  assert.equal(a.outcome, "ON_TIME");
});

test("the target is missed: late inside the buffer is BEST_EFFORT_AT_RISK, out of reach before the window ends is BEST_EFFORT_UNREACHABLE; the target is not lowered", () => {
  const late = advise({ ceilings: [{ name: "owner_maximum", watts: 3900 }] });
  assert.equal(late.advice, "BEST_EFFORT");
  assert.equal(late.reason, "BEST_EFFORT_AT_RISK");
  assert.equal(late.outcome, "LATE");
  assert.equal(late.targetWillBeMissed, true);
  assert.equal(late.rateW, 3900);
  assert.equal(late.neededW, null);
  assert.ok((late.marginMin as number) < 0);
  assert.match(late.summary, /target will be missed/);
  assert.equal(late.decision.targetSocPct, 80);
  const gone = advise({ ceilings: [{ name: "owner_maximum", watts: 1500 }] });
  assert.equal(gone.advice, "BEST_EFFORT");
  assert.equal(gone.reason, "BEST_EFFORT_UNREACHABLE");
  assert.equal(gone.outcome, "MISSED");
  assert.equal(gone.targetWillBeMissed, true);
  assert.equal(gone.rateW, 1500);
  assert.equal(gone.finishInMin, null);
  assert.equal(gone.decision.targetSocPct, 80);
});

test("the deadline has passed but the window is open: best effort, the target will be missed; the window over: no advice", () => {
  const passed = advise({ elapsedMin: 320, socPct: 60 });
  assert.equal(passed.status, "DEADLINE_PASSED");
  assert.equal(passed.advice, "BEST_EFFORT");
  assert.equal(passed.reason, "BEST_EFFORT_DEADLINE_PASSED");
  assert.equal(passed.targetWillBeMissed, true);
  assert.equal(passed.rateW, passed.safeMaxW);
  assert.equal(passed.outcome, "MISSED", "not reached even at the safe maximum before the window ends");
  assert.equal(passed.finishInMin, null);
  // late but still before the window ends: LATE, not MISSED
  const lateOnly = advise({ elapsedMin: 310, socPct: 75 });
  assert.equal(lateOnly.reason, "BEST_EFFORT_DEADLINE_PASSED");
  assert.equal(lateOnly.outcome, "LATE");
  assert.ok(lateOnly.finishInMin !== null && lateOnly.finishInMin <= 50);
  assert.equal(lateOnly.targetWillBeMissed, true);
  const over = advise({ elapsedMin: 360, socPct: 60 });
  assert.equal(over.advice, "NO_ADVICE");
  assert.equal(over.reason, "WINDOW_ENDED");
  assert.equal(over.outcome, "MISSED");
  assert.equal(over.targetWillBeMissed, true);
  assert.equal(over.rateW, null);
  const noBuffer = advise({ bufferMin: 120, chargeWindow: { startMin: 0, endMin: 2 * 60, clockDay: ORDINARY }, elapsedMin: 0 });
  assert.ok(noBuffer.codes.includes("BUFFER_AS_LONG_AS_WINDOW"));
  assert.equal(noBuffer.reason, "BEST_EFFORT_DEADLINE_PASSED");
});

test("at or above the target there is nothing to charge", () => {
  const a = advise({ socPct: 80 });
  assert.equal(a.advice, "NOTHING_TO_CHARGE");
  assert.equal(a.reason, "AT_TARGET");
  assert.equal(a.outcome, "AT_TARGET");
  assert.equal(a.rateW, null);
  assert.equal(a.targetWillBeMissed, false);
  assert.equal(advise({ socPct: 100, targetSocPct: 90 }).advice, "NOTHING_TO_CHARGE");
});

// ---- no advice on missing, stale or implausible data ---------------------------------------------------------------------------------

test("missing, stale or implausible data gives NO advice and says why", () => {
  const cases: Array<[string, Partial<GentleAdviceInput>, AdviceReason, "UNKNOWN" | "MISSED"]> = [
    ["no SOC", { socPct: null }, "NO_SOC", "UNKNOWN"],
    ["SOC not a number", { socPct: Number.NaN }, "NO_SOC", "UNKNOWN"],
    ["SOC out of range", { socPct: 140 }, "NO_SOC", "UNKNOWN"],
    ["stale SOC", { socAgeMin: 16 }, "STALE_SOC", "UNKNOWN"],
    ["unknown SOC age", { socAgeMin: null }, "STALE_SOC", "UNKNOWN"],
    ["a SOC far below the previous one", { socPct: 30, previousSoc: { socPct: 60, elapsedMin: 0 }, elapsedMin: 20 }, "SOC_IMPLAUSIBLE", "UNKNOWN"],
    ["a SOC far above the previous one", { socPct: 90, previousSoc: { socPct: 20, elapsedMin: 0 }, elapsedMin: 10 }, "SOC_IMPLAUSIBLE", "UNKNOWN"],
    ["no ceiling known", { ceilings: [] }, "NO_SAFE_CEILING", "UNKNOWN"],
    ["only unknown ceilings", { ceilings: [{ name: "a", watts: null }, { name: "b", watts: undefined }] }, "NO_SAFE_CEILING", "UNKNOWN"],
    ["only a stale ceiling", { ceilings: [{ name: "a", watts: 5000, ageMin: 500 }] }, "NO_SAFE_CEILING", "UNKNOWN"],
    ["the ceiling is below the practical minimum", { ceilings: [{ name: "a", watts: 400 }] }, "CEILING_BELOW_MIN", "MISSED"],
    ["a known grid limit that is stale", { household: { gridImportLimitW: 9000, gridImportLimitAgeMin: 500, demandNowW: 500, demandAgeMin: 1 } }, "GRID_LIMIT_STALE", "UNKNOWN"],
    ["a known grid limit and no demand at all (the default policy)", { household: { gridImportLimitW: 9000 } }, "HOUSEHOLD_UNUSABLE", "UNKNOWN"],
    ["a known grid limit and an invalid demand", { household: { gridImportLimitW: 9000, demandNowW: -5, demandAgeMin: 1 } }, "HOUSEHOLD_INVALID", "UNKNOWN"],
    ["the grid headroom is below the practical minimum", { household: { gridImportLimitW: 1500, demandNowW: 1200, demandAgeMin: 1, demandProfile: [{ fromInMin: 0, watts: 1200 }], demandProfileAgeMin: 1 } }, "HEADROOM_BELOW_MIN", "MISSED"],
    ["an invalid target", { targetSocPct: 3 }, "INVALID_INPUT", "UNKNOWN"],
    ["a window with no length", { chargeWindow: { startMin: 60, endMin: 60, clockDay: ORDINARY } }, "INVALID_INPUT", "UNKNOWN"],
    ["a window that starts inside the hour a spring change skips", { chargeWindow: { startMin: 150, endMin: 360, clockDay: { changeAtMin: 120, deltaMin: 60 } } }, "INVALID_INPUT", "UNKNOWN"],
  ];
  for (const [name, over, reason, outcome] of cases) {
    const a = advise(over);
    assert.equal(a.advice, "NO_ADVICE", name);
    assert.equal(a.reason, reason, name);
    assert.equal(a.outcome, outcome, name);
    assert.equal(a.targetWillBeMissed, outcome === "MISSED", name);
    assert.equal(a.rateW, null, name);
    assert.equal(a.rateAmps, null, name);
    assert.equal(a.neededW, null, name);
    assert.ok(a.explanation.length > 0 && a.explanation[0] !== "", name + ": says why");
    assert.match(a.summary, /^No advice: /, name);
  }
  // a missing input object is no advice either
  for (const bad of [null, undefined, 7, "x"]) {
    const a = adviseGentleRate(bad as unknown as GentleAdviceInput);
    assert.equal(a.advice, "NO_ADVICE");
    assert.equal(a.reason, "INVALID_INPUT");
    assert.equal(a.rateW, null);
  }
});

test("an assumed demand is only used when asked for, and the advice is then DEGRADED, never a normal OK", () => {
  const house = { gridImportLimitW: 9000 };
  assert.equal(advise({ household: house }).reason, "HOUSEHOLD_UNUSABLE");
  const a = advise({ household: house, policy: { unknownDemandPolicy: "ASSUME_PROVISIONAL" } });
  assert.equal(a.advice, "RATE");
  assert.equal(a.status, "DEGRADED");
  assert.equal(a.degraded, true);
  assert.ok(a.codes.includes("ASSUMED_DEMAND"));
  assert.equal(a.outcome, "ON_TIME");
});

test("a binding grid headroom caps the rate: the highest safe rate is the smaller of the ceiling and the cap", () => {
  const house = { gridImportLimitW: 5200, demandNowW: 500, demandAgeMin: 1, demandProfile: [{ fromInMin: 0, watts: 500 }], demandProfileAgeMin: 1 };
  const a = advise({ household: house, policy: { setpointBasis: "GRID_AC" } });
  // cap = 5200 - 500 x 1.2 = 4600 W grid side: below the 5000 W ceiling (so it is the highest safe rate) and above the 4100 W the target needs
  assert.equal(a.limitedBy, "GRID_HEADROOM");
  assert.equal(a.safeMaxW, 4600);
  assert.equal(a.rateW, 4100);
  assert.equal(a.reason, "RATE_GENTLEST");
  const tight = advise({ household: { ...house, gridImportLimitW: 4400 }, policy: { setpointBasis: "GRID_AC" } });
  // cap = 4400 - 600 = 3800 W < 4100 W needed: best effort at the cap, the target will be missed
  assert.equal(tight.limitedBy, "GRID_HEADROOM");
  assert.equal(tight.safeMaxW, 3800);
  assert.equal(tight.rateW, 3800);
  assert.equal(tight.advice, "BEST_EFFORT");
  assert.equal(tight.targetWillBeMissed, true);
});

// ---- no memory, no side effects, deterministic -----------------------------------------------------------------------------------------

test("the advice has no memory: stateful inputs of the full model cannot change it", () => {
  const plain = advise();
  const sneaky = adviseGentleRate({ ...base, currentSetpointW: 3000, lastChangeElapsedMin: 0, changesUsed: 99, totalChangesUsed: 99, staticPlanRateW: 2000, policy: { fallbackPolicy: "USE_STATIC_PLAN" } } as unknown as GentleAdviceInput);
  assert.deepEqual(sneaky, plain);
  const noData = adviseGentleRate({ ...base, socPct: null, currentSetpointW: 3000, policy: { fallbackPolicy: "KEEP_CURRENT" } } as unknown as GentleAdviceInput);
  assert.equal(noData.advice, "NO_ADVICE");
  assert.equal(noData.rateW, null, "no fallback rate is ever advised");
  assert.equal(noData.decision.fallback.policy, "NONE");
  assert.equal(noData.decision.fallback.setpointW, null);
});

test("pure and deterministic: a frozen input is accepted, never changed, and the same input gives the same advice every time", () => {
  const r = rng(77);
  for (let n = 0; n < 150; n++) {
    const input = randomInput(r);
    const snapshot = JSON.stringify(input);
    deepFreeze(input);
    const a = adviseGentleRate(input);
    const b = adviseGentleRate(input);
    assert.deepEqual(a, b);
    assert.equal(JSON.stringify(input), snapshot);
    assert.equal(JSON.stringify(a), JSON.stringify(b));
    assert.deepEqual(JSON.parse(JSON.stringify(a)), JSON.parse(JSON.stringify(b)));
  }
});

// ---- hard limits, outcomes and reason codes over many random states --------------------------------------------------------------------

test("hard limits and consistency over random states: never above the ceiling or the cap, never below the practical minimum, one closed reason", () => {
  const r = rng(424242);
  const seen = new Map<AdviceReason, number>();
  for (let n = 0; n < 1500; n++) {
    const input = randomInput(r);
    const a = adviseGentleRate(input);
    seen.set(a.reason, (seen.get(a.reason) ?? 0) + 1);
    assert.ok(ADVICE_REASONS.includes(a.reason), "closed reason list: " + a.reason);
    assert.equal(a.actuationSupported, false);
    assert.equal(a.guarantee, "NONE");
    assert.equal(a.decision.targetSocPct, input.targetSocPct, "the target is never lowered");
    assert.equal(a.targetWillBeMissed, a.outcome === "LATE" || a.outcome === "MISSED");
    assert.equal(a.degraded, a.status === "DEGRADED");
    if (a.rateW === null) {
      assert.ok(a.advice === "NO_ADVICE" || a.advice === "NOTHING_TO_CHARGE");
      assert.equal(a.rateAmps, null);
      continue;
    }
    assert.ok(a.advice === "RATE" || a.advice === "BEST_EFFORT");
    assert.equal(a.rateW % STEP, 0, "a multiple of the step");
    assert.ok(a.rateW >= a.minRateW, "never below the practical minimum");
    assert.ok(a.rateW <= (a.safeMaxW as number), "never above the safe maximum");
    assert.ok(a.rateW <= P.hardMaxW, "never above the editor's maximum");
    const knownCeil = Math.min(...input.ceilings.filter((c) => typeof c.watts === "number").map((c) => c.watts as number));
    assert.ok(a.rateW <= knownCeil, "never above the smallest known ceiling");
    if (a.advice === "RATE") {
      assert.equal(a.outcome, "ON_TIME");
      assert.equal(a.rateW, a.neededW, "exactly what is needed");
      assert.ok((a.marginMin as number) >= 0);
      assert.ok(a.reason === "RATE_GENTLEST" || a.reason === "RATE_AT_PRACTICAL_MINIMUM" || a.reason === "RATE_AT_SAFE_MAXIMUM");
    } else {
      assert.ok(a.outcome === "LATE" || a.outcome === "MISSED");
      assert.equal(a.targetWillBeMissed, true);
      assert.equal(a.rateW, a.safeMaxW, "a best effort is the highest safe rate");
    }
  }
  // the sweep reaches the main reasons (the rest are reached by the hand-written cases above)
  for (const reason of ["RATE_GENTLEST", "RATE_AT_PRACTICAL_MINIMUM", "BEST_EFFORT_AT_RISK", "BEST_EFFORT_UNREACHABLE", "AT_TARGET", "NO_SOC", "STALE_SOC", "NO_SAFE_CEILING"] as AdviceReason[]) {
    assert.ok((seen.get(reason) ?? 0) > 0, "the random sweep produced " + reason);
  }
});

test("the reason list is closed, every reason is reachable, and a decision that fits no rule is NO_ADVICE, never a rate (fail closed)", () => {
  assert.equal(new Set(ADVICE_REASONS).size, ADVICE_REASONS.length);
  const reached = new Set<AdviceReason>();
  const scenarios: Partial<GentleAdviceInput>[] = [
    {}, { socPct: 79, chargeWindow: { startMin: 0, endMin: 8 * 60, clockDay: ORDINARY } }, { ceilings: [{ name: "a", watts: 4100 }] }, { ceilings: [{ name: "a", watts: 3900 }] },
    { ceilings: [{ name: "a", watts: 1500 }] }, { elapsedMin: 320, socPct: 60 }, { socPct: 80 }, { socPct: null }, { socAgeMin: 30 }, { socPct: 30, previousSoc: { socPct: 60, elapsedMin: 0 }, elapsedMin: 20 },
    { ceilings: [] }, { ceilings: [{ name: "a", watts: 400 }] }, { household: { gridImportLimitW: 1500, demandNowW: 1200, demandAgeMin: 1, demandProfile: [{ fromInMin: 0, watts: 1200 }], demandProfileAgeMin: 1 } }, { household: { gridImportLimitW: 9000 } },
    { household: { gridImportLimitW: 9000, demandNowW: -1, demandAgeMin: 1 } }, { household: { gridImportLimitW: 9000, gridImportLimitAgeMin: 900, demandNowW: 1, demandAgeMin: 1 } }, { elapsedMin: 360, socPct: 60 }, { targetSocPct: 3 },
  ];
  for (const s of scenarios) reached.add(advise(s).reason);
  for (const reason of ADVICE_REASONS) if (reason !== "NO_SETPOINT" && reason !== "RATE_AT_SAFE_MAXIMUM") assert.ok(reached.has(reason), "reachable: " + reason);
  assert.ok(advise({ ceilings: [{ name: "a", watts: 4100 }] }).reason === "RATE_AT_SAFE_MAXIMUM");
  // a decision of the model that matches no rule here
  const ok = planGentle({ ...base, currentSetpointW: null, lastChangeElapsedMin: null, changesUsed: 0 } as GentleInput);
  const noRate: GentleDecision = { ...ok, setpointW: null };
  const a = adviceFromDecision(noRate, base);
  assert.equal(a.advice, "NO_ADVICE");
  assert.equal(a.reason, "NO_SETPOINT");
  assert.equal(a.rateW, null);
  const lateOk: GentleDecision = { ...ok, marginMin: -1 };
  assert.equal(adviceFromDecision(lateOk, base).advice, "NO_ADVICE", "an OK decision that is not on time is not offered as a rate");
  assert.equal(adviceFromDecision(lateOk, base).rateW, null, "and no rate leaks out of a refused decision");
  const noMargin: GentleDecision = { ...ok, marginMin: null };
  assert.equal(adviceFromDecision(noMargin, base).advice, "NO_ADVICE");
  assert.equal(adviceFromDecision(noMargin, base).rateW, null);
  assert.equal(adviceFromDecision(noRate, base).rateW, null);
  const exactlyOnTime: GentleDecision = { ...ok, marginMin: 0 };
  assert.equal(adviceFromDecision(exactlyOnTime, base).advice, "RATE", "a projected finish exactly at the deadline is on time");
  assert.equal(adviceFromDecision(exactlyOnTime, base).outcome, "ON_TIME");
  const odd = { ...ok, status: "SOMETHING_NEW" } as unknown as GentleDecision;
  assert.equal(adviceFromDecision(odd, base).reason, "NO_SETPOINT");
  const noDataNoCode: GentleDecision = { ...ok, status: "NO_DATA", setpointW: null, codes: ["START"] };
  assert.equal(adviceFromDecision(noDataNoCode, base).reason, "NO_SETPOINT");
});

// ---- monotone --------------------------------------------------------------------------------------------------------------------------

/** The rate the advice stands for on a sweep: the advised rate, 0 when there is nothing to charge, undefined when there is no advice. */
const effective = (a: GentleAdvice): number | undefined => (a.advice === "NOTHING_TO_CHARGE" ? 0 : a.rateW === null ? undefined : a.rateW);

function checkMonotone(name: string, input: GentleAdviceInput, grid: number[], make: (x: number) => Partial<GentleAdviceInput>, direction: "up" | "down"): number {
  let prev: number | undefined;
  let compared = 0;
  for (const x of grid) {
    const e = effective(adviseGentleRate({ ...input, ...make(x) }));
    if (e === undefined) continue;
    if (prev !== undefined) {
      compared++;
      if (direction === "up") assert.ok(e >= prev, name + ": the rate must not fall (" + prev + " -> " + e + ") at " + x + " for " + JSON.stringify(input));
      else assert.ok(e <= prev, name + ": the rate must not rise (" + prev + " -> " + e + ") at " + x + " for " + JSON.stringify(input));
    }
    prev = e;
  }
  return compared;
}

test("monotone: a higher SOC never raises the rate; a higher target, less time, a longer buffer or a larger capacity never lower it (random states, fine grids)", () => {
  const r = rng(9001);
  const counts = { soc: 0, target: 0, elapsed: 0, buffer: 0, capacity: 0, band: 0 };
  const range = (from: number, to: number, step: number) => Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, i) => from + i * step);
  for (let n = 0; n < 60; n++) {
    const input: GentleAdviceInput = { ...randomInput(r), socPct: 50, socAgeMin: 1, elapsedMin: 0, params: undefined, household: undefined };
    const real = windowRealMinutes(input.chargeWindow.startMin, input.chargeWindow.endMin, input.chargeWindow.clockDay) as number;
    counts.soc += checkMonotone("soc", input, range(0, 100, 1), (x) => ({ socPct: x }), "down");
    counts.target += checkMonotone("target", input, range(10, 100, 1), (x) => ({ targetSocPct: x }), "up");
    counts.elapsed += checkMonotone("elapsed", input, range(0, real, 5), (x) => ({ elapsedMin: x }), "up");
    counts.buffer += checkMonotone("buffer", input, range(0, 120, 5), (x) => ({ bufferMin: x }), "up");
    counts.capacity += checkMonotone("capacity", input, range(5, 80, 1), (x) => ({ capacityKwh: x }), "up");
    counts.band += checkMonotone("band", input, range(0, 30, 1), (x) => ({ capacityUpPct: x }), "up");
  }
  for (const [k, v] of Object.entries(counts)) assert.ok(v > 200, "the sweep compared enough pairs for " + k + ": " + v);
});

test("monotone through the unmodified gentle profile and with a learned capacity too", () => {
  const r = rng(31337);
  for (let n = 0; n < 30; n++) {
    const input: GentleAdviceInput = { ...randomInput(r), socPct: 40, socAgeMin: 1, elapsedMin: 0, household: undefined, params: { ...GENTLE_RECOMMENDED_PARAMS }, learnedCapacityKwh: 20 + Math.floor(r() * 30) };
    checkMonotone("soc", input, Array.from({ length: 101 }, (_, i) => i), (x) => ({ socPct: x }), "down");
    checkMonotone("learned", input, Array.from({ length: 60 }, (_, i) => 5 + i), (x) => ({ learnedCapacityKwh: x }), "up");
  }
});

// ---- the cautions that ride along --------------------------------------------------------------------------------------------------------

test("warnings: a safe ceiling given with no age is said to be taken as current (and only those); a dated one is not; the advice itself does not change", () => {
  const plain = advise();
  assert.deepEqual(plain.warnings.map((w) => w.code), ["CEILING_AGE_UNKNOWN"]);
  assert.match(plain.warnings[0]!.text, /owner_maximum, battery_max_charge/);
  assert.doesNotMatch(plain.warnings[0]!.text, /grid_charge_current/, "an unknown ceiling is not a ceiling that is trusted");
  const dated = advise({ ceilings: [{ name: "a", watts: 5000, ageMin: 0 }, { name: "b", watts: 6200, ageMin: 5 }, { name: "c", watts: null }] });
  assert.deepEqual(dated.warnings, []);
  const mixed = advise({ ceilings: [{ name: "a", watts: 5000, ageMin: 3 }, { name: "b", watts: 6200 }, { name: "c", watts: 7000, ageMin: null }] });
  assert.match(mixed.warnings[0]!.text, /: b, c\./);
  assert.equal(advise({ ceilings: [{ name: "a", watts: 5000, ageMin: 3 }, { name: "b", watts: 6200 }] }).rateW, advise({ ceilings: [{ name: "a", watts: 5000, ageMin: 3 }, { name: "b", watts: 6200, ageMin: 3 }] }).rateW, "a warning never changes the rate");
  assert.equal(plain.rateW, 4100);
  assert.match(advise({ ceilings: [{ name: "z", watts: 0 }] }).warnings[0]!.text, /: z\./, "a ceiling of zero is a known ceiling");
  assert.deepEqual(advise({ ceilings: [] }).warnings, [], "no ceiling at all, nothing taken as current");
  assert.deepEqual(advise({ ceilings: [{ name: "x", watts: -5 }, { name: "y", watts: Number.NaN }] }).warnings, [], "an invalid figure is not a ceiling that is trusted");
});

test("warnings: a 100 percent target carries the top-of-charge caution on every kind of advice, a lower target does not", () => {
  const dated: NamedCeiling[] = [{ name: "a", watts: 6000, ageMin: 1 }];
  for (const over of [{}, { socPct: 100 }, { socPct: null }, { ceilings: [{ name: "a", watts: 1500, ageMin: 1 }] }, { elapsedMin: 360 }] as Partial<GentleAdviceInput>[]) {
    const a = advise({ targetSocPct: 100, ceilings: dated, ...over });
    assert.ok(a.warnings.some((w) => w.code === "TOP_OF_CHARGE_TAIL"), JSON.stringify(over));
    assert.match(a.warnings.find((w) => w.code === "TOP_OF_CHARGE_TAIL")!.text, /keep charging for a while after the reading reaches 100/);
  }
  assert.deepEqual(advise({ targetSocPct: 99, ceilings: dated }).warnings, []);
  assert.deepEqual(advise({ targetSocPct: 80, ceilings: dated }).warnings, []);
  const both = advise({ targetSocPct: 100 });
  assert.deepEqual(both.warnings.map((w) => w.code), ["CEILING_AGE_UNKNOWN", "TOP_OF_CHARGE_TAIL"]);
});

test("warnings never change the advice: with and without the cautions' triggers the rate, the outcome and the reason are the model's, and bad input has none", () => {
  const r = rng(2468);
  for (let n = 0; n < 300; n++) {
    const input = randomInput(r);
    const a = adviseGentleRate(input);
    const dated = adviseGentleRate({ ...input, ceilings: input.ceilings.map((c) => ({ ...c, ageMin: 1 })) });
    assert.equal(a.rateW, dated.rateW);
    assert.equal(a.reason, dated.reason);
    assert.equal(a.outcome, dated.outcome);
    assert.ok(Array.isArray(a.warnings));
    assert.ok(a.warnings.every((w) => (w.code === "CEILING_AGE_UNKNOWN" || w.code === "TOP_OF_CHARGE_TAIL") && w.text.length > 20));
    assert.ok(!dated.warnings.some((w) => w.code === "CEILING_AGE_UNKNOWN"));
  }
  assert.deepEqual(adviseGentleRate(null as unknown as GentleAdviceInput).warnings, []);
  assert.deepEqual(adviseGentleRate({ ...base, ceilings: "x" as unknown as NamedCeiling[] }).warnings, []);
  assert.deepEqual(adviseGentleRate({ ...base, ceilings: [null, 3] as unknown as NamedCeiling[] }).warnings, []);
});

// ---- the rate as a current -------------------------------------------------------------------------------------------------------------

test("the same rate as a current: at the lowest pack voltage, never above the current limit, null when the voltage is unknown or invalid", () => {
  const a = advise({ battery: { volts: 52, minVolts: 48 } });
  assert.equal(a.rateW, 4100);
  assert.equal(a.rateAmps, Math.round((4100 / 48) * 10) / 10);
  const lowerOnly = advise({ battery: { volts: 48, minVolts: 52 } });
  assert.equal(lowerOnly.rateAmps, Math.round((4100 / 48) * 10) / 10, "the lower of the two voltages is used");
  assert.equal(advise({ battery: { volts: 50 } }).rateAmps, 82);
  assert.equal(advise({ battery: { volts: 50, maxChargeAmps: 60 } }).rateAmps, 60, "never above the current limit");
  assert.equal(advise({ battery: { volts: 50, maxChargeAmps: 0 } }).rateAmps, 0);
  for (const volts of [null, 0, -5, Number.NaN]) assert.equal(advise({ battery: { volts } }).rateAmps, null, "volts " + volts);
  assert.equal(advise({ battery: null }).rateAmps, null);
  assert.equal(advise().rateAmps, null, "no pack data, no current");
  assert.equal(advise({ socPct: null, battery: { volts: 50 } }).rateAmps, null, "no advice, no current");
  assert.equal(advise({ socPct: 90, battery: { volts: 50 } }).rateAmps, null, "nothing to charge, no current");
});

// ---- the margins it states ---------------------------------------------------------------------------------------------------------------

test("the margins the rate already carries are stated: buffer, capacity band, SOC offset, top hold and the assumed taper", () => {
  const a = advise();
  assert.deepEqual({ ...a.margins, marginMin: 0 }, { bufferMin: 60, capacityBandPct: 6, socOffsetPct: 0.5, topHoldMin: 0, taperStartSocPct: P.taperStartSocPct, taperEndFraction: P.taperEndFraction, marginMin: 0 });
  assert.equal(a.margins.marginMin, a.marginMin);
  const full = advise({ targetSocPct: 100, params: { topHoldMin: 30, socResolutionPct: 2, taperStartSocPct: 95 } });
  assert.equal(full.margins.topHoldMin, 30);
  assert.equal(full.margins.socOffsetPct, 1);
  assert.equal(full.margins.taperStartSocPct, 95);
  assert.equal(full.margins.bufferMin, 60);
  // a larger finish-early buffer shows in the stated margin and raises the rate
  const bigger = advise({ bufferMin: 120 });
  assert.ok((bigger.rateW as number) > (a.rateW as number));
  assert.equal(bigger.margins.bufferMin, 120);
});

test("the summary says the target will be missed whenever it will", () => {
  const r = rng(5);
  for (let n = 0; n < 500; n++) {
    const a = adviseGentleRate(randomInput(r));
    if (a.targetWillBeMissed) assert.match(a.summary, /missed/i, a.reason);
    if (a.advice === "RATE") assert.doesNotMatch(a.summary, /missed/i);
    assert.ok(a.summary.length > 10);
  }
});

test("the README documents the advice, its limits and the proof needed before any live use", () => {
  const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
  assert.match(readme, /Gentle rate advice/);
  assert.match(readme, /gentleAdvice\.ts/);
  assert.match(readme, /adviseGentleRate/);
  assert.match(readme, /GENTLE_LIVE_ACTUATION_PROOF\.md/);
  const proof = readFileSync(new URL("../GENTLE_LIVE_ACTUATION_PROOF.md", import.meta.url), "utf8");
  assert.match(proof, /read[- ]only/i);
  assert.match(proof, /independent/i);
});

// ---- a random state generator (seeded; includes invalid and unusual values) -----------------------------------------------------------

function randomInput(r: () => number): GentleAdviceInput {
  const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(r() * xs.length)] as T;
  const startMin = Math.floor(r() * 288) * 5;
  const length = 120 + Math.floor(r() * 97) * 5;
  const target = r() < 0.2 ? 100 : 10 + Math.floor(r() * 91);
  const ceilings: NamedCeiling[] = [];
  const kinds = 1 + Math.floor(r() * 3);
  for (let i = 0; i < kinds; i++) {
    const u = r();
    const watts = u < 0.12 ? null : u < 0.2 ? undefined : r() < 0.05 ? 300 : 1000 + Math.floor(r() * 80) * 100;
    ceilings.push({ name: "c" + i, watts: watts as number | null | undefined });
  }
  const soc = r() < 0.05 ? null : Math.floor(r() * 1010) / 10;
  const input: GentleAdviceInput = {
    targetSocPct: target,
    bufferMin: pick([0, 5, 15, 30, 60, 90, 120]),
    chargeWindow: { startMin, endMin: (startMin + length) % 1440, clockDay: ORDINARY },
    elapsedMin: r() < 0.1 ? length + 5 : Math.floor(r() * length),
    socPct: soc === null ? null : Math.min(soc, 100),
    socAgeMin: r() < 0.05 ? 99 : Math.floor(r() * 10),
    capacityKwh: 5 + Math.floor(r() * 55),
    capacityUpPct: Math.floor(r() * 16),
    ceilings,
  };
  if (r() < 0.15) input.learnedCapacityKwh = 10 + Math.floor(r() * 40);
  if (r() < 0.2) input.household = { gridImportLimitW: 3000 + Math.floor(r() * 90) * 100, demandNowW: Math.floor(r() * 3000), demandAgeMin: Math.floor(r() * 20), demandProfile: [{ fromInMin: 0, watts: Math.floor(r() * 3000) }], demandProfileAgeMin: Math.floor(r() * 60) };
  if (r() < 0.1) input.params = { minW: pick([300, 500, 800, 1000]), taperStartSocPct: pick([50, 90, 98]), topHoldMin: pick([0, 20, 60]) };
  return input;
}

test("round 3 F9: a safe ceiling whose name cannot be converted to text (an object with no prototype) does not make the advice throw; the warning lists it as unnamed", () => {
  const bare = Object.create(null) as never;
  const a = advise({ ceilings: [{ name: bare, watts: 5000 }, { name: "owner_maximum", watts: 6200 }] });
  assert.deepEqual(a.warnings.map((w) => w.code), ["CEILING_AGE_UNKNOWN"]);
  assert.match(a.warnings[0]!.text, /: unnamed, owner_maximum\./);
  assert.equal(a.actuationSupported, false);
  // the ordinary names are listed as before
  assert.match(advise({ ceilings: [{ name: "owner_maximum", watts: 5000 }, { name: "b", watts: 6200 }] }).warnings[0]!.text, /: owner_maximum, b\./);
});
