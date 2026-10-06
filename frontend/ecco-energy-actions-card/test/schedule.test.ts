import { test } from "node:test";
import assert from "node:assert/strict";
import {
  classifySchedule,
  isScheduleRejected,
  isScheduleBlocked,
  scheduleFieldsLocked,
  resolveDisplayState,
  scheduleArmServiceCall,
  scheduleCancelServiceCall,
  scheduleSetStartServiceCall,
  scheduleSetNumberServiceCall,
  effectiveSchedulePowerMax,
} from "../src/schedule.ts";
import { canStartFreePower, canToggleArm, type FreePowerVisualState } from "../src/freePowerState.ts";

test("no schedule: armed null/false -> hidden banner", () => {
  assert.equal(classifySchedule({ armed: false }), "hidden");
  assert.equal(classifySchedule({ armed: null }), "hidden");
});

test("schedule armed: confirmed armed=true -> armed banner", () => {
  assert.equal(classifySchedule({ armed: true }), "armed");
});

test("schedule rejected: last_result starting REJECTED is detected", () => {
  assert.equal(isScheduleRejected("REJECTED - scheduled start must be in the future"), true);
  assert.equal(isScheduleRejected("REJECTED - scheduled 9000W outside safe range 500-8000W"), true);
});

test("schedule rejected: unrelated last_result values are not treated as a rejection", () => {
  assert.equal(isScheduleRejected("ARMED - 2026-09-23 02:00:00 • 90 min • 3000W"), false);
  assert.equal(isScheduleRejected("CANCELLED - scheduled event disarmed"), false);
  assert.equal(isScheduleRejected("STARTED OK - 3000W for 90 min"), false);
  assert.equal(isScheduleRejected(undefined), false);
  assert.equal(isScheduleRejected(""), false);
});

test("schedule blocked: last_result starting BLOCKED is detected distinctly from REJECTED", () => {
  assert.equal(isScheduleBlocked("BLOCKED - effective grid charge power limit unavailable"), true);
  assert.equal(isScheduleBlocked("REJECTED - scheduled start must be in the future"), false);
});

test("schedule countdown: a future start parses and formats via the shared time helpers", async () => {
  const { parseLocalTimestamp, formatCountdown } = await import("../src/utils/time.ts");
  const now = Date.parse("2026-09-22T22:48:00");
  const target = parseLocalTimestamp("2026-09-23 02:00:00")!;
  assert.equal(formatCountdown(target.getTime(), now), "3h 12m");
});

test("schedule fields locked while armed, unlocked otherwise", () => {
  assert.equal(scheduleFieldsLocked(true), true);
  assert.equal(scheduleFieldsLocked(false), false);
  assert.equal(scheduleFieldsLocked(null), false);
});

test("cancel service mapping targets the existing cancel script via script.turn_on", () => {
  const call = scheduleCancelServiceCall("script.ecco_free_power_cancel_schedule");
  assert.deepEqual(call, {
    domain: "script",
    service: "turn_on",
    data: { entity_id: "script.ecco_free_power_cancel_schedule" },
  });
});

test("Arm Schedule service mapping targets the schedule's own input_boolean via input_boolean.turn_on", () => {
  const call = scheduleArmServiceCall("input_boolean.ecco_free_power_schedule_armed");
  assert.deepEqual(call, {
    domain: "input_boolean",
    service: "turn_on",
    data: { entity_id: "input_boolean.ecco_free_power_schedule_armed" },
  });
});

test("manual Arm and schedule Arm remain distinct service domains/entities", () => {
  const scheduleArm = scheduleArmServiceCall("input_boolean.ecco_free_power_schedule_armed");
  // The manual arm path (see ecco-energy-actions-card.ts's _toggleArm) calls
  // switch.turn_on/turn_off on the firmware write_enable switch - a
  // completely different domain and entity to the schedule arm above.
  const manualArmDomain = "switch";
  const manualArmEntity = "switch.ecco_clock_dongle_free_power_write_enable";
  assert.notEqual(scheduleArm.domain, manualArmDomain);
  assert.notEqual((scheduleArm.data as { entity_id: string }).entity_id, manualArmEntity);
});

test("manual Start remains gated by manual write_enable (armed) only - schedule state is not a parameter", () => {
  // canStartFreePower/canToggleArm take only the top-level FreePowerVisualState -
  // structurally incapable of being influenced by schedule armed/rejected/
  // countdown state, since that state is never passed to them.
  assert.equal(canStartFreePower.length, 1);
  assert.equal(canToggleArm.length, 1);
  assert.equal(canStartFreePower("armed"), true);
  assert.equal(canStartFreePower("ready"), false);
});

test("scheduleSetStartServiceCall maps to input_datetime.set_datetime", () => {
  const call = scheduleSetStartServiceCall("input_datetime.ecco_free_power_schedule_start", "2026-09-23 02:00:00");
  assert.deepEqual(call, {
    domain: "input_datetime",
    service: "set_datetime",
    data: { entity_id: "input_datetime.ecco_free_power_schedule_start", datetime: "2026-09-23 02:00:00" },
  });
});

test("scheduleSetNumberServiceCall maps to input_number.set_value", () => {
  const call = scheduleSetNumberServiceCall("input_number.ecco_free_power_schedule_power", 3000);
  assert.deepEqual(call, {
    domain: "input_number",
    service: "set_value",
    data: { entity_id: "input_number.ecco_free_power_schedule_power", value: 3000 },
  });
});

test("effectiveSchedulePowerMax clamps down to the site's configured limit when lower", () => {
  assert.equal(effectiveSchedulePowerMax(8000, 6000), 6000);
});

test("effectiveSchedulePowerMax never raises above the entity's own max", () => {
  assert.equal(effectiveSchedulePowerMax(8000, 9000), 8000);
});

test("effectiveSchedulePowerMax falls back to the entity max when the limit is absent/invalid", () => {
  assert.equal(effectiveSchedulePowerMax(8000, null), 8000);
  assert.equal(effectiveSchedulePowerMax(8000, 0), 8000);
  assert.equal(effectiveSchedulePowerMax(8000, NaN), 8000);
});

// ---------------------------------------------------------------------
// resolveDisplayState: ACTIVE and every hardware/safety state override
// schedule cosmetics; only the plain "ready" state can be upgraded to
// "scheduled" once the schedule is confirmed armed.
// ---------------------------------------------------------------------
const HARDWARE_STATES: FreePowerVisualState[] = [
  "unavailable",
  "recovery_attention",
  "deferred",
  "busy",
  "active",
  "armed",
];

for (const state of HARDWARE_STATES) {
  test(`resolveDisplayState never overrides hardware state "${state}" with "scheduled"`, () => {
    assert.equal(resolveDisplayState(state, "armed"), state);
  });
}

test("resolveDisplayState upgrades plain ready + confirmed-armed schedule to scheduled", () => {
  assert.equal(resolveDisplayState("ready", "armed"), "scheduled");
});

test("resolveDisplayState leaves ready alone when no schedule is armed", () => {
  assert.equal(resolveDisplayState("ready", "hidden"), "ready");
});
