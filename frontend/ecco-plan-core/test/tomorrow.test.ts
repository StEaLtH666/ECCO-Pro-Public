import { test } from "node:test";
import assert from "node:assert/strict";
import { buildTomorrowPlan } from "../src/tomorrow.ts";
import { planGentleCharge } from "../src/chargePlanner.ts";
import { reduceSettings } from "../src/settings.ts";
import { exampleSettings } from "./fixtures.ts";

test("no advice: every advice-derived item is an explicit unknown, never a number", () => {
  for (const advice of [null, undefined, {}]) {
    const t = buildTomorrowPlan({ advice, settings: exampleSettings() });
    for (const item of [t.importKwh, t.exportKwh, t.solarKwh, t.chargeFinishMin]) {
      assert.equal(item.known, false);
      assert.ok(!("value" in item));
      assert.ok(item.state);
    }
    assert.equal(t.confidence.known, false);
    assert.equal(t.confidence.level, "UNKNOWN");
    assert.ok(t.why.some((w) => /unknown/.test(w.text)));
  }
});

test("advice numbers pass through as PROPOSED; malformed ones are unknown, not coerced", () => {
  const t = buildTomorrowPlan({
    advice: { expectedImportKwh: 12.5, expectedExportKwh: -3, expectedSolarKwh: Number.NaN, confidence: "HIGH", why: ["Cheap night rate", 7, "  ", "x".repeat(500)] },
    settings: exampleSettings(),
  });
  assert.deepEqual(t.importKwh, { known: true, value: 12.5, state: "PROPOSED", origin: "intelligence", simulated: false });
  assert.equal(t.exportKwh.known, false);
  assert.equal(t.solarKwh.known, false);
  assert.equal(t.confidence.level, "HIGH");
  const adviceWhy = t.why.filter((w) => w.origin === "advice");
  assert.equal(adviceWhy.length, 2);
  assert.equal(adviceWhy[1]?.text.length, 200);
  assert.equal(buildTomorrowPlan({ advice: { confidence: "SURE" }, settings: exampleSettings() }).confidence.level, "UNKNOWN");
});

test("non-HIGH confidence is stated, and nothing is presented as firm", () => {
  const t = buildTomorrowPlan({ advice: { confidence: "MEDIUM", expectedSolarKwh: 9 }, settings: exampleSettings() });
  assert.ok(t.why.some((w) => /holds rather than acts/.test(w.text)));
  assert.equal(t.solarKwh.known && t.solarKwh.state, "PROPOSED");
});

test("charge finish: from the planner it is labelled simulated and carries the weakest field state; unknown with neither", () => {
  const settings = exampleSettings();
  const plan = planGentleCharge({ startSocPct: 20, targetSocPct: 70, capacityKwh: 30, capacityUpPct: 6, windowMin: 330, bufferMin: 60 });
  const t = buildTomorrowPlan({ advice: null, settings, chargePlan: plan });
  assert.ok(t.chargeFinishMin.known);
  assert.equal(t.chargeFinishMin.simulated, true);
  assert.equal(t.chargeFinishMin.origin, "planner");
  assert.equal(t.chargeFinishMin.state, "PROPOSED");
  assert.equal(t.chargeFinishMin.value, 233, "23:30 window start plus about 263 simulated minutes (3600 W)");
  const none = buildTomorrowPlan({ advice: null, settings, chargePlan: planGentleCharge({ startSocPct: 80, targetSocPct: 70, capacityKwh: 30, capacityUpPct: 6, windowMin: 330, bufferMin: 60 }) });
  assert.equal(none.chargeFinishMin.known, false);
  assert.match((none.chargeFinishMin as { reason: string }).reason, /No overnight charge/);
  const withAdvice = buildTomorrowPlan({ advice: { chargeFinishMin: 4 * 60 }, settings, chargePlan: plan });
  assert.ok(withAdvice.chargeFinishMin.known && withAdvice.chargeFinishMin.origin === "intelligence" && withAdvice.chargeFinishMin.value === 240);
});

test("an overrunning planner result is surfaced in the why list", () => {
  const plan = planGentleCharge({ startSocPct: 20, targetSocPct: 70, capacityKwh: 30, capacityUpPct: 6, windowMin: 360, bufferMin: 20, taperMin: 30 });
  assert.equal(plan.status, "BUFFER_TOO_SMALL");
  const t = buildTomorrowPlan({ advice: null, settings: exampleSettings(), chargePlan: plan });
  assert.ok(t.why.some((w) => /Buffer too small/.test(w.text) && /simulated, not measured/.test(w.text)));
});

test("reserve is a setting: its state is the field's state, so it is verified only after a read-back", () => {
  let s = exampleSettings();
  let t = buildTomorrowPlan({ advice: null, settings: s });
  assert.equal(t.reservePct.known && t.reservePct.state, "PROPOSED");
  s = reduceSettings(s, { type: "readback", path: "reserve.backupPct", observed: 40 }).settings;
  t = buildTomorrowPlan({ advice: null, settings: s });
  assert.equal(t.reservePct.known && t.reservePct.state, "APPLIED_VERIFIED");
});
