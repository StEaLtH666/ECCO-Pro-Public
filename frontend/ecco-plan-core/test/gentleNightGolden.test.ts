// Golden master of the v1 / v2 Gentle model (planGentle, adviseGentleRate): the night planner is added next to it and changes nothing there. The pins were taken
// from the unchanged model at this commit's parent; a change in any of these numbers means the older model moved. Where the v1 assumptions still apply (a target
// below its taper start, no household input) the night planner is never gentler than v1 (it is more pessimistic on purpose); above the knee it is allowed to differ
// and does (the saved nights show a fall, not v1's linear slope).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { adviseGentleRate } from "../src/gentleAdvice.ts";
import { maxChargePowerCeiling } from "../src/gentleController.ts";
import { planGentleNight } from "../src/gentleNight.ts";
import { rng } from "./fixtures.ts";

const ORD = { changeAtMin: 0, deltaMin: 0 } as const;
interface C { target: number; soc: number; cap: number; buf: number; el: number }
const v1 = (c: C) =>
  adviseGentleRate({
    targetSocPct: c.target, bufferMin: c.buf, chargeWindow: { startMin: 30, endMin: 330, clockDay: ORD }, elapsedMin: c.el, socPct: c.soc, socAgeMin: 1, capacityKwh: c.cap, capacityUpPct: 6,
    ceilings: [maxChargePowerCeiling(8000, 8000)],
  });
const night = (c: C) =>
  planGentleNight({ targetSocPct: c.target, bufferMin: c.buf, chargeWindow: { startMin: 30, endMin: 330 }, clockDay: ORD, elapsedMin: c.el, socPct: c.soc, socAgeMin: 1, capacityKwh: c.cap, ceilings: [maxChargePowerCeiling(8000, 8000)] });

const GOLDEN: Array<[C, string, number, string, number, number]> = [
  [{ target: 80, soc: 20, cap: 30, buf: 60, el: 0 }, "RATE_GENTLEST", 5100, "OK", 238.3, 240],
  [{ target: 60, soc: 20, cap: 31.7, buf: 60, el: 0 }, "RATE_GENTLEST", 3600, "OK", 238.8, 240],
  [{ target: 70, soc: 35, cap: 25, buf: 30, el: 60 }, "RATE_GENTLEST", 2900, "OK", 204.9, 210],
  [{ target: 85, soc: 10, cap: 31.7, buf: 0, el: 0 }, "RATE_GENTLEST", 5400, "OK", 296.7, 300],
  [{ target: 90, soc: 50, cap: 20, buf: 60, el: 30 }, "RATE_GENTLEST", 2600, "OK", 208.6, 210],
  [{ target: 100, soc: 30, cap: 31.7, buf: 60, el: 0 }, "RATE_AT_SAFE_MAXIMUM", 8000, "OK", 218.8, 240],
];

test("golden master: the v1 / v2 advice is unchanged for six fixed nights (rate, reason, status, finish and deadline)", () => {
  for (const [c, reason, rate, status, finish, deadline] of GOLDEN) {
    const a = v1(c);
    assert.equal(a.reason, reason, JSON.stringify(c));
    assert.equal(a.rateW, rate, JSON.stringify(c));
    assert.equal(a.status, status);
    assert.equal(a.finishInMin, finish);
    assert.equal(a.deadlineInMin, deadline);
    assert.equal(a.actuationSupported, false);
  }
});

test("golden master: the older model's sources are untouched by this change (the night planner is a separate module)", () => {
  const ctrl = readFileSync(new URL("../src/gentleController.ts", import.meta.url), "utf8");
  assert.doesNotMatch(ctrl, /gentleNight/);
  const adv = readFileSync(new URL("../src/gentleAdvice.ts", import.meta.url), "utf8");
  assert.doesNotMatch(adv, /gentleNight/);
  const idx = readFileSync(new URL("../src/index.ts", import.meta.url), "utf8");
  assert.doesNotMatch(idx, /gentleNight|gentleAdvice/);
});

test("where v1's assumptions still apply (target at most 85, plateau only) the night planner is never gentler than v1 (seeded sweep)", () => {
  const r = rng(1234);
  let compared = 0;
  for (let i = 0; i < 500; i++) {
    const c: C = { target: 40 + Math.floor(r() * 46), soc: 5 + Math.floor(r() * 60), cap: 15 + Math.round(r() * 250) / 10, buf: 5 * Math.floor(r() * 25), el: Math.floor(r() * 100) };
    const a = v1(c);
    const n = night(c);
    if (a.rateW === null || n.now.setpointW === null || a.advice !== "RATE" || n.status !== "OK") continue;
    compared++;
    assert.ok(n.now.setpointW >= a.rateW, JSON.stringify(c) + ": night " + n.now.setpointW + " v1 " + a.rateW);
  }
  assert.ok(compared > 150, "compared " + compared);
});

test("above the knee the two models are allowed to differ, and do: v1's linear slope calls a full charge on time that the measured shape calls at risk", () => {
  const c: C = { target: 100, soc: 30, cap: 31.7, buf: 60, el: 0 };
  assert.equal(v1(c).status, "OK");
  assert.equal(night(c).status, "TARGET_AT_RISK");
  assert.equal(night(c).now.setpointW, 8000);
});
