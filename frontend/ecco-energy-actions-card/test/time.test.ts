import { test } from "node:test";
import assert from "node:assert/strict";
import { parseLocalTimestamp, formatLocalTimestamp, formatWeekdayDateTime, formatCountdown } from "../src/utils/time.ts";

test("parses the firmware's strftime local-time format", () => {
  const d = parseLocalTimestamp("2026-09-22 14:32:07");
  assert.ok(d);
  assert.equal(d.getFullYear(), 2026);
  assert.equal(d.getMonth(), 8); // 0-indexed - September
  assert.equal(d.getDate(), 22);
  assert.equal(d.getHours(), 14);
  assert.equal(d.getMinutes(), 32);
  assert.equal(d.getSeconds(), 7);
});

test("also parses Home Assistant's input_datetime state shape (identical format)", () => {
  const d = parseLocalTimestamp("2026-09-23 02:00:00");
  assert.ok(d);
  assert.equal(d.getMonth(), 8);
  assert.equal(d.getDate(), 23);
  assert.equal(d.getHours(), 2);
});

test("returns null for non-timestamp prose values", () => {
  assert.equal(parseLocalTimestamp("Inactive"), null);
  assert.equal(parseLocalTimestamp("Active - end time unavailable"), null);
  assert.equal(parseLocalTimestamp(undefined), null);
  assert.equal(parseLocalTimestamp(""), null);
});

test("formatLocalTimestamp round-trips through parseLocalTimestamp", () => {
  const original = new Date(2026, 8, 23, 2, 0, 0);
  const text = formatLocalTimestamp(original);
  assert.equal(text, "2026-09-23 02:00:00");
  const parsed = parseLocalTimestamp(text);
  assert.ok(parsed);
  assert.equal(parsed.getTime(), original.getTime());
});

test("formatCountdown shows hours+minutes above an hour", () => {
  const now = Date.parse("2026-09-22T10:00:00");
  const target = now + (2 * 3600 + 15 * 60) * 1000;
  assert.equal(formatCountdown(target, now), "2h 15m");
});

test("formatCountdown shows minutes+seconds under an hour", () => {
  const now = Date.parse("2026-09-22T10:00:00");
  const target = now + (5 * 60 + 3) * 1000;
  assert.equal(formatCountdown(target, now), "5m 03s");
});

test("formatCountdown shows only seconds under a minute", () => {
  const now = Date.parse("2026-09-22T10:00:00");
  const target = now + 42 * 1000;
  assert.equal(formatCountdown(target, now), "42s");
});

test("formatWeekdayDateTime matches the task's example format", () => {
  // 2026-09-23 is a Wednesday, not the task's illustrative "Tue" - the
  // exact weekday depends on the real calendar date used, so this pins the
  // FORMAT shape rather than a specific weekday string.
  const d = new Date(2026, 8, 23, 2, 0, 0);
  assert.equal(formatWeekdayDateTime(d), "Wed 23 Sep • 02:00");
});

test("formatCountdown returns null once the target has passed", () => {
  const now = Date.parse("2026-09-22T10:00:00");
  assert.equal(formatCountdown(now - 1000, now), null);
  assert.equal(formatCountdown(now, now), null);
});
