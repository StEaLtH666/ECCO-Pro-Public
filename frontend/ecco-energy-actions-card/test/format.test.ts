import { test } from "node:test";
import assert from "node:assert/strict";
import { formatPower, formatDurationMinutes, toNumber, toBoolean } from "../src/utils/format.ts";

test("formatPower switches to kW above 1000 W", () => {
  assert.equal(formatPower(500), "500 W");
  assert.equal(formatPower(999), "999 W");
  assert.equal(formatPower(1000), "1.00 kW");
  assert.equal(formatPower(4200), "4.20 kW");
});

test("formatPower handles missing values", () => {
  assert.equal(formatPower(null), "--");
  assert.equal(formatPower(undefined), "--");
  assert.equal(formatPower(NaN), "--");
});

test("formatDurationMinutes", () => {
  assert.equal(formatDurationMinutes(45), "45 min");
  assert.equal(formatDurationMinutes(60), "1h");
  assert.equal(formatDurationMinutes(90), "1h 30m");
  assert.equal(formatDurationMinutes(null), "--");
});

test("toNumber", () => {
  assert.equal(toNumber("500"), 500);
  assert.equal(toNumber("unavailable"), null);
  assert.equal(toNumber("unknown"), null);
  assert.equal(toNumber(undefined), null);
  assert.equal(toNumber("not-a-number"), null);
});

test("toBoolean", () => {
  assert.equal(toBoolean("on"), true);
  assert.equal(toBoolean("off"), false);
  assert.equal(toBoolean("unavailable"), null);
  assert.equal(toBoolean(undefined), null);
});
