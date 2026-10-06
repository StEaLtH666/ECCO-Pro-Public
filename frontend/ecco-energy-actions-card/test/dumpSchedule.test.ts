// 2026-09-26 pre-live hardening: Dump to Grid schedule / latched-value /
// recovery presentation tests. Pure-function behaviour plus one structural
// check on the component source (the LATER panel and schedule banner must
// never reach the firmware directly).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  classifyDump,
  canStartDump,
  resolveDumpDisplayState,
  dumpDisplayStateLabel,
  resolveLatchedExportPower,
  resolveLatchedStopSoc,
  dumpRecoveryControlsVisible,
  type DumpVisualState,
} from "../src/dumpState.ts";
import {
  classifySchedule,
  scheduleFieldsLocked,
  scheduleArmServiceCall,
  scheduleCancelServiceCall,
  scheduleSetNumberServiceCall,
  scheduleSetStartServiceCall,
} from "../src/schedule.ts";
import { formatPercent } from "../src/utils/format.ts";

const DUMP_SCHEDULE = {
  armed: "input_boolean.ecco_dump_to_grid_schedule_armed",
  start: "input_datetime.ecco_dump_to_grid_schedule_start",
  duration: "input_number.ecco_dump_to_grid_schedule_duration",
  power: "input_number.ecco_dump_to_grid_schedule_power",
  stop_soc: "input_number.ecco_dump_to_grid_schedule_stop_soc",
  last_result: "input_text.ecco_dump_to_grid_schedule_last_result",
  status: "sensor.ecco_dump_to_grid_schedule_status",
  cancel: "script.ecco_dump_to_grid_cancel_schedule",
};

test("a confirmed armed Dump schedule upgrades ONLY the plain ready state to scheduled", () => {
  assert.equal(resolveDumpDisplayState("ready", true), "scheduled");
  assert.equal(dumpDisplayStateLabel("scheduled"), "Scheduled");
  for (const s of ["unavailable", "recovery_attention", "deferred", "busy", "active", "armed"] as DumpVisualState[]) {
    assert.equal(resolveDumpDisplayState(s, true), s, `schedule must not conceal ${s}`);
  }
});

test("an unconfirmed / unavailable schedule never shows as scheduled", () => {
  assert.equal(resolveDumpDisplayState("ready", false), "ready");
  assert.equal(resolveDumpDisplayState("ready", null), "ready");
  assert.equal(classifySchedule({ armed: null }), "hidden");
});

test("an outstanding restore obligation stays visible even while a schedule is armed", () => {
  const state = classifyDump({
    active: false,
    armed: false,
    operationInProgress: false,
    snapshotValid: true,
    statusText: "REJECTED - saved snapshot pending restore/recovery",
  });
  assert.equal(resolveDumpDisplayState(state, true), "deferred");
});

test("schedule fields lock while armed (cancel, edit, re-arm is the only path)", () => {
  assert.equal(scheduleFieldsLocked(true), true);
  assert.equal(scheduleFieldsLocked(false), false);
});

test("Dump schedule staging maps onto exactly the package's helpers and services", () => {
  assert.deepEqual(scheduleSetNumberServiceCall(DUMP_SCHEDULE.power, 1000), {
    domain: "input_number",
    service: "set_value",
    data: { entity_id: "input_number.ecco_dump_to_grid_schedule_power", value: 1000 },
  });
  assert.deepEqual(scheduleSetNumberServiceCall(DUMP_SCHEDULE.stop_soc, 60).data, {
    entity_id: "input_number.ecco_dump_to_grid_schedule_stop_soc",
    value: 60,
  });
  assert.deepEqual(scheduleSetNumberServiceCall(DUMP_SCHEDULE.duration, 2).domain, "input_number");
  assert.deepEqual(scheduleSetStartServiceCall(DUMP_SCHEDULE.start, "2026-09-27 14:00:00"), {
    domain: "input_datetime",
    service: "set_datetime",
    data: { entity_id: "input_datetime.ecco_dump_to_grid_schedule_start", datetime: "2026-09-27 14:00:00" },
  });
  const arm = scheduleArmServiceCall(DUMP_SCHEDULE.armed);
  assert.deepEqual(arm, { domain: "input_boolean", service: "turn_on", data: { entity_id: DUMP_SCHEDULE.armed } });
  const cancel = scheduleCancelServiceCall(DUMP_SCHEDULE.cancel);
  assert.deepEqual(cancel, { domain: "script", service: "turn_on", data: { entity_id: DUMP_SCHEDULE.cancel } });
  for (const call of [arm, cancel]) {
    assert.notEqual(call.domain, "switch", "schedule arm/cancel must never touch the firmware write_enable switch");
    assert.notEqual(call.domain, "button", "schedule arm/cancel must never press a firmware button");
  }
});

test("manual START stays gated on the manual arm regardless of any schedule", () => {
  assert.equal(canStartDump("ready"), false);
  assert.equal(canStartDump("armed"), true);
});

test("ACTIVE shows the LATCHED export power, never a newly edited staged value", () => {
  // Latched sensor wins.
  assert.equal(resolveLatchedExportPower(1000, "ACTIVE - VERIFIED OK; target 1000W export - TRACKING - battery ceiling 1000W; Stop SOC 40%"), 1000);
  // Latched sensor unknown -> the firmware's own ACTIVE status text (the
  // TARGET, not the dynamically-adjusted ceiling - see dumpState.ts).
  assert.equal(resolveLatchedExportPower(null, "ACTIVE - VERIFIED OK; target 700W export - SATURATED HIGH - battery ceiling 3000W (target not fully achievable); Stop SOC 40%"), 700);
  // Neither available -> unknown ("--"), NOT the staged number.
  assert.equal(resolveLatchedExportPower(null, "REJECTED - Dump to Grid already active"), null);
  assert.equal(resolveLatchedExportPower(null, undefined), null);
});

test("ACTIVE shows the LATCHED Stop SOC the firmware enforces", () => {
  assert.equal(resolveLatchedStopSoc(35, "ACTIVE - VERIFIED OK; target 1000W export - TRACKING - battery ceiling 1000W; Stop SOC 40%"), 35);
  assert.equal(resolveLatchedStopSoc(null, "ACTIVE - VERIFIED OK; target 1000W export - TRACKING - battery ceiling 1000W; Stop SOC 40%"), 40);
  assert.equal(resolveLatchedStopSoc(null, "Inactive"), null);
  assert.equal(formatPercent(null), "--");
  assert.equal(formatPercent(40), "40%");
});

// 2026-09-26 adversarial review (M3): the firmware never claims a target
// grid export is being achieved while saturated - resolveLatchedExportPower
// must still extract the TARGET (not the ceiling named in the same string)
// from every V1.1 status shape, including the two saturated ones.
test("resolveLatchedExportPower extracts the TARGET, not the ceiling, from every V1.1 controller state", () => {
  assert.equal(resolveLatchedExportPower(null, "ACTIVE - VERIFIED OK; target 500W export - SATURATED LOW - battery ceiling 500W (PV export already exceeds target); Stop SOC 25%"), 500);
  assert.equal(resolveLatchedExportPower(null, "ACTIVE - VERIFIED OK; target 500W export - SATURATED HIGH - battery ceiling 3000W (target not fully achievable); Stop SOC 25%"), 500);
  assert.equal(resolveLatchedExportPower(null, "ACTIVE - VERIFIED OK; target 500W export - SETTLING - battery ceiling 500W; Stop SOC 25%"), 500);
  assert.equal(resolveLatchedExportPower(null, "ACTIVE - VERIFIED OK; target 500W export - WAITING FOR FRESH GRID - battery ceiling 1500W; Stop SOC 25%"), 500);
});

test("recovery controls appear only for an operator decision with a live obligation", () => {
  assert.equal(dumpRecoveryControlsVisible("OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State", true), true);
  assert.equal(dumpRecoveryControlsVisible("ACCEPT REFUSED - inverter still shows Allow Export in a non-original configuration", true), true);
  assert.equal(dumpRecoveryControlsVisible("OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State", false), false);
  assert.equal(dumpRecoveryControlsVisible("OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State", null), false);
  assert.equal(dumpRecoveryControlsVisible("END DEFERRED - previous restore attempt failed; waiting out retry backoff", true), false);
  assert.equal(dumpRecoveryControlsVisible("START FAILED - verify mismatch or write error", true), false);
  assert.equal(dumpRecoveryControlsVisible(undefined, true), false);
});

// 2026-09-26 final pre-OTA review: a lockout that follows an ACTIVE lease
// keeps binary_sensor dump_to_grid_active ON (dump_active_persisted is only
// cleared by a verified restore). A refused Accept / an un-armed recovery
// press must still land in the attention panel with the recovery controls -
// never fall through to "Active / Exporting up to N W".
test("a refused Accept or un-armed recovery press stays in attention, even with the lease flag still on", () => {
  const lockout = { armed: false, operationInProgress: false, snapshotValid: true } as const;
  for (const statusText of [
    "ACCEPT REFUSED - inverter still shows Allow Export in a non-original configuration (Dump to Grid residue) - use Force Restore Original, or set Load Limit to a non-export mode first",
    "ACCEPT REFUSED - no fresh configuration readback since the last Dump to Grid operation - wait for the next 60s poll (Read-Only Configuration Polling must be on)",
    "REJECTED - arm Dump to Grid Recovery Arm first",
  ]) {
    for (const active of [true, false]) {
      const state = classifyDump({ ...lockout, active, statusText });
      assert.equal(state, "recovery_attention", `${statusText} (active=${active})`);
      assert.equal(resolveDumpDisplayState(state, true), "recovery_attention", "a schedule must not conceal it");
    }
    assert.equal(dumpRecoveryControlsVisible(statusText, true), true, statusText);
  }
  // The ordinary START arm rejection is still a safe, idle state.
  assert.equal(
    classifyDump({ active: false, armed: false, operationInProgress: false, snapshotValid: false, statusText: "REJECTED - arm Dump to Grid Write Enable first" }),
    "ready"
  );
});

// Structural: the Dump LATER panel and schedule banner only ever call the
// schedule.ts service builders (input_* helpers / the cancel script) - never
// a firmware button, the write_enable switch, or any Modbus-adjacent entity.
test("Dump LATER panel / banner have no direct firmware path", () => {
  const src = readFileSync(new URL("../src/ecco-energy-actions-card.ts", import.meta.url), "utf-8");
  const body = (name: string): string => {
    const start = src.indexOf(`  private ${name}(`);
    assert.ok(start >= 0, `${name} not found`);
    const next = src.indexOf("\n  private ", start + 10);
    return src.slice(start, next < 0 ? undefined : next);
  };
  for (const name of ["_renderDumpLaterPanel", "_renderDumpScheduleBanner", "_commitDumpScheduleNumber"]) {
    const b = body(name);
    assert.ok(!/_callService\(\s*"(button|switch|number)"/.test(b), `${name} must not call button/switch/number services`);
    assert.ok(!/write_enable|\.start\b(?!Text|Date)|end_restore/.test(b.replace(/schedule\.start/g, "")), `${name} must not reference firmware START/END/arm entities`);
  }
});
