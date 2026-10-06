import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveHomeW, HOME_FALLBACK_MIN_W } from "../src/config.ts";

test("native Home credible (non-zero) -> native used, even if it disagrees with the balance", () => {
  // inverter 1000 + grid 500 would derive to 1500, but a credible non-zero
  // native reading is never second-guessed.
  assert.equal(resolveHomeW(1200, 1000, 500), 1200);
});

test("native Home unavailable -> derived used", () => {
  assert.equal(resolveHomeW(null, 1240, 1810), 3050);
});

test("native Home unavailable and inputs also unavailable -> degrades to 0, never null/NaN", () => {
  assert.equal(resolveHomeW(null, null, null), 0);
  assert.equal(resolveHomeW(null, 1240, null), 0);
  assert.equal(resolveHomeW(null, null, 1810), 0);
});

test("native Home exactly 0W while the balance clearly implies load -> derived used (the documented bug)", () => {
  // The live Dump-to-Grid sample: PV 763W, battery 632W discharging,
  // inverter AC out 1.24kW, grid 1.81kW importing, native Home 0W.
  assert.equal(resolveHomeW(0, 1240, 1810), 3050);
});

test("native Home exactly 0W and the balance is also near zero -> genuine zero load is NOT fabricated", () => {
  assert.equal(resolveHomeW(0, 0, 0), 0);
  assert.equal(resolveHomeW(0, 10, -5), 0); // 5W derived, well under the fallback margin
});

test("the fallback margin boundary is exclusive at HOME_FALLBACK_MIN_W", () => {
  assert.equal(resolveHomeW(0, HOME_FALLBACK_MIN_W, 0), 0, "exactly at the margin: native 0 stands");
  assert.equal(resolveHomeW(0, HOME_FALLBACK_MIN_W + 1, 0), HOME_FALLBACK_MIN_W + 1, "just past the margin: derived used");
});

test("derived value is clamped at 0, never negative, when export exceeds inverter output", () => {
  // inverter 200W out, grid -500W (exporting 500W) - balance is negative,
  // must never be reported as -300W of "load".
  assert.equal(resolveHomeW(null, 200, -500), 0);
});

test("a credible non-zero native reading is clamped at 0 too (defence in depth)", () => {
  assert.equal(resolveHomeW(-5, 1000, 1000), 0);
});

test("after the Dump-to-Grid lease ends and telemetry settles, native is trusted again", () => {
  // PV 753W, battery 2.54kW discharging, inverter AC out 3.03kW, grid 0.21kW
  // importing, native Home 3.05kW - a credible non-zero native reading.
  assert.equal(resolveHomeW(3050, 3030, 210), 3050);
});
