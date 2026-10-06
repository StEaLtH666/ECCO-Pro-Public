import { test } from "node:test";
import assert from "node:assert/strict";
import {
  classifyFreePower,
  canStartFreePower,
  canEndRestore,
  canToggleArm,
  type FreePowerClassifyInput,
} from "../src/freePowerState.ts";

const base: FreePowerClassifyInput = {
  active: false,
  armed: false,
  operationInProgress: false,
  statusText: "Inactive",
};

test("unavailable when any core entity is null (unavailable/unknown)", () => {
  assert.equal(classifyFreePower({ ...base, active: null }), "unavailable");
  assert.equal(classifyFreePower({ ...base, armed: null }), "unavailable");
  assert.equal(classifyFreePower({ ...base, operationInProgress: null }), "unavailable");
});

test("plain idle/ready state", () => {
  assert.equal(classifyFreePower(base), "ready");
});

test("armed state", () => {
  assert.equal(classifyFreePower({ ...base, armed: true, statusText: "Inactive" }), "armed");
});

test("active state", () => {
  assert.equal(
    classifyFreePower({ ...base, active: true, armed: true, statusText: "ACTIVE" }),
    "active"
  );
});

test("active takes priority over a stale armed flag", () => {
  // Firmware behaviour: write_enable can still read on while a session is
  // already active - active must win, never fall back to "armed".
  assert.equal(classifyFreePower({ ...base, active: true, armed: true }), "active");
});

test("busy from operation_in_progress with no special status text", () => {
  assert.equal(
    classifyFreePower({ ...base, operationInProgress: true, statusText: "Inactive" }),
    "busy"
  );
});

test("busy from literal STARTING status text", () => {
  assert.equal(
    classifyFreePower({
      ...base,
      operationInProgress: true,
      statusText: "STARTING - taking fresh inverter snapshot",
    }),
    "busy"
  );
});

test("busy from literal RESTORING status text", () => {
  assert.equal(
    classifyFreePower({
      ...base,
      active: true,
      operationInProgress: true,
      statusText: "RESTORING - confirming live inverter state before writing",
    }),
    "busy"
  );
});

test("deferred from literal END DEFERRED status text (the live-proven case)", () => {
  assert.equal(
    classifyFreePower({
      ...base,
      active: true,
      operationInProgress: true,
      statusText: "END DEFERRED - Modbus bus busy with another transaction; watchdog will retry",
    }),
    "deferred"
  );
});

test("recovery_attention from RECOVERY REQUIRED", () => {
  assert.equal(
    classifyFreePower({ ...base, statusText: "RECOVERY REQUIRED - saved snapshot found" }),
    "recovery_attention"
  );
});

test("recovery_attention from OPERATOR DECISION REQUIRED", () => {
  assert.equal(
    classifyFreePower({
      ...base,
      active: true,
      statusText: "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Free Power; press End Free Power to retry",
    }),
    "recovery_attention"
  );
});

test("recovery_attention from RESTORE BLOCKED", () => {
  assert.equal(
    classifyFreePower({
      ...base,
      active: true,
      statusText:
        "RESTORE BLOCKED - live inverter state matches neither the saved snapshot nor Free Power's intended state; operator decision required",
    }),
    "recovery_attention"
  );
});

test("recovery_attention from a bare FAILED status", () => {
  assert.equal(
    classifyFreePower({
      ...base,
      statusText: "START FAILED - could not capture complete inverter snapshot",
    }),
    "recovery_attention"
  );
});

test("REJECTED status text does NOT trigger recovery_attention - system stays ready", () => {
  assert.equal(
    classifyFreePower({
      ...base,
      statusText: "REJECTED - arm Free Power Write Enable first",
    }),
    "ready"
  );
});

test("RESTORED OK status text does NOT trigger busy or attention - falls through to boolean state", () => {
  assert.equal(
    classifyFreePower({ ...base, statusText: "RESTORED OK - original inverter settings verified" }),
    "ready"
  );
});

test("canStartFreePower is true only in the armed state", () => {
  assert.equal(canStartFreePower("armed"), true);
  for (const s of ["ready", "active", "busy", "deferred", "recovery_attention", "unavailable"] as const) {
    assert.equal(canStartFreePower(s), false, `expected canStartFreePower(${s}) to be false`);
  }
});

test("canEndRestore is disabled only while busy or unavailable", () => {
  assert.equal(canEndRestore("busy"), false);
  assert.equal(canEndRestore("unavailable"), false);
  for (const s of ["ready", "armed", "active", "deferred", "recovery_attention"] as const) {
    assert.equal(canEndRestore(s), true, `expected canEndRestore(${s}) to be true`);
  }
});

test("canToggleArm only in ready/armed", () => {
  assert.equal(canToggleArm("ready"), true);
  assert.equal(canToggleArm("armed"), true);
  for (const s of ["active", "busy", "deferred", "recovery_attention", "unavailable"] as const) {
    assert.equal(canToggleArm(s), false, `expected canToggleArm(${s}) to be false`);
  }
});
