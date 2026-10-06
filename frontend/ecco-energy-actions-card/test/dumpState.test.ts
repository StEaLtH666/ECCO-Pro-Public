import { test } from "node:test";
import assert from "node:assert/strict";
import {
  classifyDump,
  canStartDump,
  canEndDump,
  canToggleDumpArm,
  type DumpClassifyInput,
} from "../src/dumpState.ts";

const base: DumpClassifyInput = {
  active: false,
  armed: false,
  operationInProgress: false,
  snapshotValid: false,
  statusText: "Inactive",
};

test("unavailable when any core entity is null (unavailable/unknown)", () => {
  assert.equal(classifyDump({ ...base, active: null }), "unavailable");
  assert.equal(classifyDump({ ...base, armed: null }), "unavailable");
  assert.equal(classifyDump({ ...base, operationInProgress: null }), "unavailable");
  assert.equal(classifyDump({ ...base, snapshotValid: null }), "unavailable");
});

test("plain idle/ready state", () => {
  assert.equal(classifyDump(base), "ready");
});

test("armed state", () => {
  assert.equal(classifyDump({ ...base, armed: true, statusText: "Inactive" }), "armed");
});

test("active state", () => {
  assert.equal(classifyDump({ ...base, active: true, armed: true, statusText: "ACTIVE" }), "active");
});

test("active takes priority over a stale armed flag", () => {
  assert.equal(classifyDump({ ...base, active: true, armed: true }), "active");
});

test("busy from operation_in_progress with no special status text", () => {
  assert.equal(classifyDump({ ...base, operationInProgress: true, statusText: "Inactive" }), "busy");
});

test("busy from literal STARTING status text", () => {
  assert.equal(
    classifyDump({ ...base, operationInProgress: true, statusText: "STARTING - taking fresh inverter snapshot" }),
    "busy"
  );
});

test("busy from literal RESTORING status text", () => {
  assert.equal(
    classifyDump({
      ...base,
      active: true,
      operationInProgress: true,
      statusText: "RESTORING - confirming live inverter state before writing",
    }),
    "busy"
  );
});

test("deferred from literal END DEFERRED status text", () => {
  assert.equal(
    classifyDump({
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
    classifyDump({ ...base, statusText: "RECOVERY REQUIRED - inverter state matches neither original nor intended" }),
    "recovery_attention"
  );
});

test("recovery_attention from OPERATOR DECISION REQUIRED", () => {
  assert.equal(
    classifyDump({
      ...base,
      active: true,
      statusText: "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; press End to retry",
    }),
    "recovery_attention"
  );
});

test("recovery_attention from a bare FAILED status", () => {
  assert.equal(
    classifyDump({ ...base, statusText: "START FAILED - could not capture complete inverter snapshot" }),
    "recovery_attention"
  );
});

test("REJECTED status text does NOT trigger recovery_attention - system stays ready", () => {
  assert.equal(classifyDump({ ...base, statusText: "REJECTED - arm Dump to Grid Write Enable first" }), "ready");
});

test("RESTORED OK status text does NOT trigger busy or attention - falls through to boolean state", () => {
  assert.equal(classifyDump({ ...base, statusText: "RESTORED OK - original inverter settings verified" }), "ready");
});

test("canStartDump is true only in the armed state", () => {
  assert.equal(canStartDump("armed"), true);
  for (const s of ["ready", "active", "busy", "deferred", "recovery_attention", "unavailable"] as const) {
    assert.equal(canStartDump(s), false, `expected canStartDump(${s}) to be false`);
  }
});

test("canEndDump is disabled only while busy or unavailable", () => {
  assert.equal(canEndDump("busy"), false);
  assert.equal(canEndDump("unavailable"), false);
  for (const s of ["ready", "armed", "active", "deferred", "recovery_attention"] as const) {
    assert.equal(canEndDump(s), true, `expected canEndDump(${s}) to be true`);
  }
});

test("canToggleDumpArm only in ready/armed", () => {
  assert.equal(canToggleDumpArm("ready"), true);
  assert.equal(canToggleDumpArm("armed"), true);
  for (const s of ["active", "busy", "deferred", "recovery_attention", "unavailable"] as const) {
    assert.equal(canToggleDumpArm(s), false, `expected canToggleDumpArm(${s}) to be false`);
  }
});

// 2026-09-26 independent review: the tile must never present Ready/Armed
// (Arm + Start enabled) while the firmware holds a durable restore
// obligation, whatever the last-published status text happens to say.
test("outstanding snapshot with a REJECTED status is deferred, never ready", () => {
  assert.equal(
    classifyDump({ ...base, snapshotValid: true, statusText: "REJECTED - saved snapshot pending restore/recovery" }),
    "deferred"
  );
});

test("outstanding snapshot while armed is deferred, never armed (Start stays disabled)", () => {
  const state = classifyDump({ ...base, armed: true, snapshotValid: true, statusText: "Inactive" });
  assert.equal(state, "deferred");
  assert.equal(canStartDump(state), false);
  assert.equal(canToggleDumpArm(state), false);
});

test("outstanding snapshot with a stale mid-start status is deferred once the operation has finished", () => {
  assert.equal(
    classifyDump({ ...base, snapshotValid: true, statusText: "Snapshot durably committed - writing export power ceiling" }),
    "deferred"
  );
});

test("an active lease still shows active while its snapshot is (correctly) valid", () => {
  assert.equal(
    classifyDump({ ...base, active: true, snapshotValid: true, statusText: "ACTIVE - VERIFIED OK; target 1000W export - TRACKING - battery ceiling 1000W; Stop SOC 25%" }),
    "active"
  );
});

test("a comms-failure restore status is attention even with the word only in lower case", () => {
  assert.equal(
    classifyDump({
      ...base,
      active: true,
      snapshotValid: true,
      statusText: "END DEFERRED - previous restore attempt failed; waiting out retry backoff; watchdog will retry automatically",
    }),
    "recovery_attention"
  );
});

test("a verified-but-uncleared marker status is not presented as ready", () => {
  assert.equal(
    classifyDump({ ...base, snapshotValid: true, statusText: "RESTORE VERIFIED - durable clear pending; will retry automatically" }),
    "deferred"
  );
});
