// ECCO status derivations: honest, entity-driven, never invented.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  classifyOnOff,
  parseLocalTimestamp,
  reserveRuntimeTile,
  resolveDaylight,
  resolveFreshness,
  resolveHealth,
  resolveReserveRuntime,
  resolveSession,
  resolveTimeToReserveMinutes,
  resolveTimeToTarget,
  resolveTouSlot,
  RESERVE_RUNTIME_STATUSES,
  type States,
} from "../src/core/status.ts";
import { formatAge, formatClockMinutes, toNumber } from "../src/core/format.ts";

// --- TOU ---------------------------------------------------------------------

const STARTS = [0, 120, 330, 960, 1140, 1410]; // 00:00 02:00 05:30 16:00 19:00 23:30

test("the current TOU slot is the one containing the local time, with the next change", () => {
  const v = resolveTouSlot(STARTS, 12 * 60 + 37, "on");
  assert.equal(v.slot, 3);
  assert.equal(v.value, "Slot 3");
  assert.equal(v.minutesToChange, 960 - 757);
  assert.equal(v.sub, "05:30–16:00 · 3 h 23 min left");
  assert.equal(resolveTouSlot(STARTS, 0, "on").slot, 1);
  assert.equal(resolveTouSlot(STARTS, 119, "on").slot, 1);
  assert.equal(resolveTouSlot(STARTS, 120, "on").slot, 2);
  assert.equal(resolveTouSlot(STARTS, 1409, "on").slot, 5);
});

test("slot 6 wraps across midnight", () => {
  assert.equal(resolveTouSlot(STARTS, 23 * 60 + 45, "on").slot, 6);
  const v = resolveTouSlot(STARTS, 23 * 60 + 45, "on");
  assert.equal(v.minutesToChange, 15);
  // A table whose slot 1 starts after midnight: 01:00 .. 23:00, slot 6 covers 23:00-01:00.
  const shifted = [60, 180, 400, 900, 1100, 1380];
  assert.equal(resolveTouSlot(shifted, 10, "on").slot, 6);
  assert.equal(resolveTouSlot(shifted, 59, "on").slot, 6);
  assert.equal(resolveTouSlot(shifted, 60, "on").slot, 1);
});

test("an unknown start or an invalid schedule gives no slot, never a guessed one", () => {
  assert.equal(resolveTouSlot([0, 120, null, 960, 1140, 1410], 600, "on").slot, null);
  assert.equal(resolveTouSlot([], 600, "on").slot, null);
  const invalid = resolveTouSlot(STARTS, 600, "off");
  assert.equal(invalid.slot, null);
  assert.equal(invalid.sub, "Schedule invalid");
  assert.equal(resolveTouSlot(STARTS, 600, "unknown").slot, 3, "a missing valid-sensor does not block a complete table");
});

// --- Sessions -----------------------------------------------------------------

const NOW = new Date(2026, 9, 26, 12, 0, 0).getTime();
const stamp = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;

test("the dongle's Ends At text is parsed as local time; anything else is not a time", () => {
  const d = parseLocalTimestamp("2026-10-26 12:47:00");
  assert.ok(d);
  assert.equal(d!.getHours(), 12);
  assert.equal(d!.getMinutes(), 47);
  assert.equal(parseLocalTimestamp("Inactive"), null);
  assert.equal(parseLocalTimestamp("Active - end time unavailable"), null);
  assert.equal(parseLocalTimestamp(undefined), null);
});

test("an active session shows the entity's own end time and the time left derived from it", () => {
  const v = resolveSession({ active: "on", endsAtText: stamp(new Date(NOW + 47 * 60000)), scheduleStatus: "ACTIVE", statusText: "ACTIVE", anyConfigured: true }, NOW, "free_power");
  assert.equal(v.phase, "active");
  assert.equal(v.value, "Active");
  assert.equal(v.sub, "Ends 12:47 · 47 min left");
  assert.ok(Math.abs(v.remainingMin! - 47) < 1e-9);
});

test("an active session whose end time is unavailable says so; no countdown is fabricated", () => {
  const v = resolveSession({ active: "on", endsAtText: "Active - end time unavailable", scheduleStatus: "ACTIVE", statusText: "ACTIVE", anyConfigured: true }, NOW, "free_power");
  assert.equal(v.phase, "active");
  assert.equal(v.endTimeUnavailable, true);
  assert.equal(v.remainingMin, null);
  assert.equal(v.sub, "Active · end time unavailable");
  const noText = resolveSession({ active: "on", endsAtText: undefined, scheduleStatus: undefined, statusText: undefined, anyConfigured: true }, NOW, "free_power");
  assert.equal(noText.sub, "Active");
  assert.equal(noText.remainingMin, null);
});

test("dump sessions add the lease's export power and stop SOC from their own sensors", () => {
  const v = resolveSession(
    { active: "on", endsAtText: stamp(new Date(NOW + 21 * 60000)), scheduleStatus: "ACTIVE", statusText: "ACTIVE", exportPowerW: 3000, stopSoc: 30, anyConfigured: true },
    NOW,
    "dump"
  );
  assert.equal(v.sub, "Ends 12:21 · 21 min left · 3000 W export · stop 30%");
});

test("armed, starting, failed, completed and standby come from the schedule status; unknown stays unknown", () => {
  const base = { active: "off" as const, endsAtText: "Inactive", statusText: "Inactive", anyConfigured: true };
  assert.equal(resolveSession({ ...base, scheduleStatus: "ARMED", scheduleAttrs: { scheduled_start: "02:00:00", duration_minutes: 120 } }, NOW, "free_power").sub, "Scheduled 02:00 · 2 h");
  assert.equal(resolveSession({ ...base, scheduleStatus: "STARTING" }, NOW, "free_power").phase, "starting");
  assert.equal(resolveSession({ ...base, scheduleStatus: "FAILED" }, NOW, "free_power").tone, "alert");
  assert.equal(resolveSession({ ...base, scheduleStatus: "COMPLETED" }, NOW, "free_power").value, "Completed");
  assert.equal(resolveSession({ ...base, scheduleStatus: "IDLE" }, NOW, "free_power").value, "Standby");
  assert.equal(resolveSession({ ...base, scheduleStatus: "IDLE" }, NOW, "dump").value, "Ready");
  assert.equal(resolveSession({ ...base, active: "unknown", scheduleStatus: undefined }, NOW, "dump").value, "--");
  assert.equal(resolveSession({ ...base, anyConfigured: false }, NOW, "dump").sub, "Not configured");
});

test("a past end time while still active is 'ending', never a negative countdown", () => {
  const v = resolveSession({ active: "on", endsAtText: stamp(new Date(NOW - 60000)), scheduleStatus: "ACTIVE", statusText: "ACTIVE", anyConfigured: true }, NOW, "free_power");
  assert.equal(v.sub, "Ends 11:59 · ending");
});

// --- FE-1 ---------------------------------------------------------------------

test("FE-1 runtime tile shows the entity's own estimate and every package status has wording", () => {
  const id = "sensor.ecco_battery_time_to_reserve";
  const rt = resolveReserveRuntime(id, resolveTimeToReserveMinutes(id, 384, "min"), { status: "discharging", minutes_low: 330, minutes_high: 440 });
  const tile = reserveRuntimeTile(rt);
  assert.equal(tile.value, "≈6h 24m");
  assert.equal(tile.sub, "to reserve · likely 5 h 30 min to 7 h 20 min");
  for (const status of RESERVE_RUNTIME_STATUSES) {
    const r = resolveReserveRuntime(id, status === "at_reserve" ? 0 : 120, { status });
    assert.notEqual(reserveRuntimeTile(r).value, "", status);
  }
  assert.equal(reserveRuntimeTile(undefined).sub, "No runtime entity");
  assert.equal(reserveRuntimeTile(resolveReserveRuntime(id, null, { status: "discharging" })).value, "--", "discharging without a value is insufficient data");
});

test("time to charge target is 'Not available' unless an entity provides it", () => {
  assert.equal(resolveTimeToTarget(undefined, {}).value, "Not available");
  const states: States = { "sensor.x": { state: "95", attributes: { unit_of_measurement: "min" } } };
  assert.equal(resolveTimeToTarget("sensor.x", states).value, "≈1h 35m");
  assert.equal(resolveTimeToTarget("sensor.x", { "sensor.x": { state: "unavailable" } }).value, "--");
});

// --- Health -------------------------------------------------------------------

test("health roll-up never hides a warning", () => {
  const states: States = {
    "sensor.ecco_health_communications": { state: "FAILED" },
    "sensor.ecco_health_rtc": { state: "DEGRADED" },
    "sensor.ecco_health_fallback": { state: "HEALTHY" },
    "sensor.ecco_health_supervision": { state: "unavailable" },
    "binary_sensor.ecco_dump_limits_attention": { state: "on" },
  };
  const ids = ["sensor.ecco_health_communications", "sensor.ecco_health_rtc", "sensor.ecco_health_fallback", "sensor.ecco_health_supervision"];
  const h = resolveHealth(ids, ["binary_sensor.ecco_dump_limits_attention"], states);
  assert.equal(h.value, "Attention");
  assert.deepEqual(h.failed, ["communications"]);
  assert.deepEqual(h.degraded, ["rtc"]);
  assert.deepEqual(h.unknown, ["supervision"]);
  assert.deepEqual(h.attention, ["dump limits attention"]);
  assert.equal(h.sub, "communications, dump limits attention");
  const degradedOnly = resolveHealth(["sensor.ecco_health_rtc", "sensor.ecco_health_fallback"], [], states);
  assert.equal(degradedOnly.value, "Degraded");
  const fine = resolveHealth(["sensor.ecco_health_fallback"], [], states);
  assert.equal(fine.value, "Nominal");
  const allUnknown = resolveHealth(["sensor.ecco_health_supervision"], [], states);
  assert.equal(allUnknown.value, "Unknown");
  assert.equal(resolveHealth([], [], states).value, "--");
});

// --- Freshness ----------------------------------------------------------------

test("freshness: telemetry offline or an old reading is stale; a fresh reading is not", () => {
  const now = Date.parse("2026-10-26T12:00:00Z");
  const states: States = {
    "sensor.a": { state: "1", last_updated: "2026-10-26T11:59:50Z" },
    "sensor.b": { state: "1", last_updated: "2026-10-26T11:50:00Z" },
  };
  const fresh = resolveFreshness(["sensor.a", "sensor.b", undefined, "sensor.missing"], states, "on", now, 180);
  assert.equal(fresh.stale, false);
  assert.equal(fresh.ageS, 10, "the newest reading counts");
  const old = resolveFreshness(["sensor.b"], states, "on", now, 180);
  assert.equal(old.stale, true);
  assert.equal(old.reason, "age");
  const offline = resolveFreshness(["sensor.a"], states, "off", now, 180);
  assert.equal(offline.stale, true);
  assert.equal(offline.reason, "telemetry_offline");
  const disabled = resolveFreshness(["sensor.b"], states, "unknown", now, 0);
  assert.equal(disabled.stale, false);
  assert.equal(resolveFreshness([], states, "unknown", now, 180).ageS, null);
  assert.equal(formatAge(10), "10 s ago");
  assert.equal(formatAge(600), "10 min ago");
  assert.equal(formatAge(null), "--");
});

// --- Misc ---------------------------------------------------------------------

test("only explicit on/off states are classified; everything else is unknown", () => {
  assert.equal(classifyOnOff("on"), "on");
  assert.equal(classifyOnOff("off"), "off");
  for (const s of ["unavailable", "unknown", "", undefined, "maybe"]) assert.equal(classifyOnOff(s), "unknown", String(s));
});

test("daylight follows sun.sun when present and only falls back to the clock otherwise", () => {
  const noon = new Date(2026, 9, 26, 12, 0);
  const midnight = new Date(2026, 9, 26, 0, 30);
  assert.equal(resolveDaylight({ state: "below_horizon", attributes: { elevation: -20 } }, noon), "night", "sun entity beats the clock");
  assert.equal(resolveDaylight({ state: "above_horizon", attributes: { elevation: 40 } }, midnight), "day");
  assert.equal(resolveDaylight({ state: "above_horizon", attributes: { elevation: 3 } }, noon), "dusk");
  assert.equal(resolveDaylight(undefined, noon), "day");
  assert.equal(resolveDaylight(undefined, midnight), "night");
});

test("number parsing treats unknown/unavailable/none as unknown", () => {
  for (const s of ["unknown", "unavailable", "", "none", "None", "abc", undefined, null]) assert.equal(toNumber(s), null, String(s));
  assert.equal(toNumber("3.5"), 3.5);
  assert.equal(formatClockMinutes(1410), "23:30");
  assert.equal(formatClockMinutes(1440), "00:00");
});
