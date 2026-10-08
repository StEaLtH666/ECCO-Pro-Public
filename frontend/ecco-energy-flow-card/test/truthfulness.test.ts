// FE-0: an unknown reading is displayed as unknown, never as a plausible
// real value. Exercises the same pure helpers the card's render path calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolveHomeW } from "../src/config.ts";
import { formatDurationMinutes, formatPower, toNumber } from "../src/utils/format.ts";
import {
  batteryStatus,
  classifyGridConnected,
  gridConnectedDisplay,
  resolveTimeToReserveMinutes,
  socDisplay,
} from "../src/utils/display.ts";

const IDLE_W = 5; // the card's IDLE_THRESHOLD_W, passed in explicitly

// --- Home ---------------------------------------------------------------

test("unknown Home (native and balance both unavailable) displays '--', not 0 W", () => {
  const homeW = resolveHomeW(toNumber("unavailable"), toNumber("unknown"), null);
  assert.equal(homeW, null);
  assert.equal(formatPower(homeW ?? undefined, undefined), "--");
});

test("a genuine 0 W Home still displays 0 W", () => {
  assert.equal(formatPower(resolveHomeW(0, 0, 0) ?? undefined, undefined), "0 W");
});

// --- Battery power --------------------------------------------------------

test("unknown battery power displays '--' status and value, not 'Idle'", () => {
  const s = batteryStatus(null, IDLE_W);
  assert.equal(s.label, "--");
  assert.notEqual(s.label, "Idle");
  assert.equal(formatPower(undefined, undefined), "--");
});

test("known battery power keeps the existing Charging/Discharging/Idle mapping", () => {
  assert.deepEqual(batteryStatus(0, IDLE_W), { label: "Idle", colour: "battery-idle" });
  assert.deepEqual(batteryStatus(IDLE_W - 1, IDLE_W), { label: "Idle", colour: "battery-idle" });
  assert.deepEqual(batteryStatus(IDLE_W, IDLE_W), { label: "Discharging", colour: "battery-discharge" });
  assert.deepEqual(batteryStatus(-IDLE_W, IDLE_W), { label: "Charging", colour: "battery-charge" });
  assert.deepEqual(batteryStatus(-2500, IDLE_W), { label: "Charging", colour: "battery-charge" });
});

// --- Grid connection ------------------------------------------------------

test("unavailable/unknown grid_connected is never a definite disconnection", () => {
  for (const raw of ["unavailable", "unknown", "", "weird", undefined]) {
    assert.equal(classifyGridConnected(raw), "unknown", String(raw));
    const d = gridConnectedDisplay(classifyGridConnected(raw));
    assert.equal(d.value, "Unknown");
    assert.equal(d.detailValue, "Unknown");
    assert.equal(d.variant, undefined, "no fault styling for an unknown signal");
    assert.notEqual(d.value, "Disconnected");
    assert.notEqual(d.detailValue, "No");
  }
});

test("explicit grid_connected states keep their meaning", () => {
  assert.equal(classifyGridConnected("on"), "connected");
  assert.equal(classifyGridConnected("true"), "connected");
  assert.equal(classifyGridConnected("off"), "disconnected");
  assert.equal(classifyGridConnected("false"), "disconnected");
  assert.deepEqual(gridConnectedDisplay("connected"), {
    value: "Connected",
    detailValue: "Yes",
    icon: "mdi:check-circle-outline",
    variant: "ok",
  });
  assert.deepEqual(gridConnectedDisplay("disconnected"), {
    value: "Disconnected",
    detailValue: "No",
    icon: "mdi:alert-circle-outline",
    variant: "fault",
  });
});

// --- SOC --------------------------------------------------------------------

test("unknown SOC has no fill (not a genuine 0%) and shows '--' when configured", () => {
  assert.deepEqual(socDisplay(toNumber("unavailable"), true), { text: "--", fillPct: null });
  assert.deepEqual(socDisplay(null, false), { text: "", fillPct: null });
});

test("a genuine 0% SOC is still a real 0% fill", () => {
  assert.deepEqual(socDisplay(0, true), { text: "0%", fillPct: 0 });
});

test("known SOC keeps rounding and 0-100 clamping", () => {
  assert.deepEqual(socDisplay(57.6, true), { text: "58%", fillPct: 57.6 });
  assert.deepEqual(socDisplay(104, true), { text: "104%", fillPct: 100 });
  assert.deepEqual(socDisplay(-3, true), { text: "-3%", fillPct: 0 });
});

// --- Duration formatting ----------------------------------------------------

test("formatDurationMinutes formats minutes, hours and days", () => {
  assert.equal(formatDurationMinutes(0), "0 min");
  assert.equal(formatDurationMinutes(0.2), "<1 min");
  assert.equal(formatDurationMinutes(1), "1 min");
  assert.equal(formatDurationMinutes(45.4), "45 min");
  assert.equal(formatDurationMinutes(59.6), "1 h");
  assert.equal(formatDurationMinutes(60), "1 h");
  assert.equal(formatDurationMinutes(125), "2 h 5 min");
  assert.equal(formatDurationMinutes(1439), "23 h 59 min");
  assert.equal(formatDurationMinutes(1440), "1 d");
  assert.equal(formatDurationMinutes(1440 + 3 * 60 + 59), "1 d 3 h");
});

test("formatDurationMinutes shows '--' for unknown, non-finite or negative input", () => {
  for (const v of [null, undefined, NaN, Infinity, -Infinity, -1]) {
    assert.equal(formatDurationMinutes(v), "--", String(v));
  }
});

// --- Optional time-to-reserve hook --------------------------------------------

test("time_to_reserve absent -> hook is inert (undefined), whatever the other inputs", () => {
  assert.equal(resolveTimeToReserveMinutes(undefined, 90, "min"), undefined);
  assert.equal(resolveTimeToReserveMinutes("", 90, undefined), undefined);
});

test("time_to_reserve present -> the entity's own value is displayed, converted only by unit", () => {
  const id = "sensor.battery_time_to_reserve";
  assert.equal(formatDurationMinutes(resolveTimeToReserveMinutes(id, toNumber("125"), undefined)), "2 h 5 min");
  assert.equal(resolveTimeToReserveMinutes(id, 125, "min"), 125);
  assert.equal(resolveTimeToReserveMinutes(id, 2.5, "h"), 150);
  assert.equal(resolveTimeToReserveMinutes(id, 300, "s"), 5);
  assert.equal(resolveTimeToReserveMinutes(id, 1, "d"), 1440);
});

test("time_to_reserve present but unknown, negative or in an uninterpretable unit -> '--'", () => {
  const id = "sensor.battery_time_to_reserve";
  assert.equal(resolveTimeToReserveMinutes(id, toNumber("unavailable"), "min"), null);
  assert.equal(resolveTimeToReserveMinutes(id, -5, "min"), null);
  assert.equal(resolveTimeToReserveMinutes(id, 30, "%"), null);
  assert.equal(resolveTimeToReserveMinutes(id, 30, "constructor"), null);
  assert.equal(resolveTimeToReserveMinutes(id, 30, 42), null);
  assert.equal(formatDurationMinutes(resolveTimeToReserveMinutes(id, null, undefined)), "--");
});

// --- No reserve logic in the card -------------------------------------------------

test("the card source calculates no reserve/ETA and hard-codes no reserve percentage", () => {
  const files = ["config.ts", "ecco-energy-flow-card.ts", "utils/format.ts", "utils/display.ts"].map((f) =>
    readFileSync(new URL(`../src/${f}`, import.meta.url), "utf-8")
  );
  for (const src of files) {
    const reserveLines = src.split("\n").filter((l) => /reserve/i.test(l));
    for (const line of reserveLines) {
      assert.doesNotMatch(line, /\b(40|10|15|5)\s*%|\b(40|10|15)\b|\+\s*5\b/, `reserve value in: ${line.trim()}`);
    }
  }
});
