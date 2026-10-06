import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyRecoveryAction } from "../src/recoveryPresentation.ts";

// Every statusText below is copied verbatim from
// firmware/ecco_clock_dongle_stage3_4_free_power.yaml's own
// id(free_power_status).publish_state(...) call sites.

test("Rule A: OPERATOR DECISION REQUIRED naming End Free Power + valid snapshot -> Retry End & Restore", () => {
  const r = classifyRecoveryAction({
    statusText:
      "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Free Power; press End Free Power to retry",
    snapshotValid: true,
  });
  assert.equal(r.actionable, true);
  assert.equal(r.actionLabel, "Retry End & Restore");
  assert.equal(r.secondary, false);
  assert.equal(r.explanation, null);
});

test("Rule A does not fire without a valid snapshot", () => {
  const r = classifyRecoveryAction({
    statusText:
      "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Free Power; press End Free Power to retry",
    snapshotValid: false,
  });
  assert.notEqual(r.actionLabel, "Retry End & Restore");
});

test("Rule B: RECOVERY REQUIRED + valid snapshot -> Restore Saved Settings", () => {
  const r = classifyRecoveryAction({
    statusText: "RECOVERY REQUIRED - saved snapshot found",
    snapshotValid: true,
  });
  assert.equal(r.actionable, true);
  assert.equal(r.actionLabel, "Restore Saved Settings");
  assert.equal(r.secondary, false);
});

test("Rule B does not fire without a valid snapshot", () => {
  const r = classifyRecoveryAction({
    statusText: "RECOVERY REQUIRED - saved snapshot found",
    snapshotValid: false,
  });
  assert.notEqual(r.actionLabel, "Restore Saved Settings");
});

for (const statusText of [
  "RESTORE VERIFY FAILED - snapshot retained for retry",
  "RESTORE VERIFY ERROR - snapshot retained for retry",
  "RESTORE VERIFY TIMEOUT - snapshot retained for retry",
  "RESTORE VERIFY REFUSED - snapshot retained for retry",
  "RESTORE WRITE FAILED - snapshot retained; will retry automatically",
]) {
  test(`Rule C: "${statusText}" + valid snapshot -> secondary End & Restore Now`, () => {
    const r = classifyRecoveryAction({ statusText, snapshotValid: true });
    assert.equal(r.actionable, true);
    assert.equal(r.actionLabel, "End & Restore Now");
    assert.equal(r.secondary, true);
  });
}

for (const statusText of [
  "RECOVERY BLOCKED - durable recovery marker exists but snapshot data is unreadable; inverter writes locked",
  "REJECTED - RECOVERY BLOCKED: durable recovery marker exists but snapshot data is unreadable; deliberate recovery required",
  "END BLOCKED - RECOVERY BLOCKED: durable recovery marker exists but snapshot data is unreadable; deliberate recovery required",
]) {
  test(`Rule D: "${statusText}" -> no actionable button, regardless of snapshot_valid`, () => {
    for (const snapshotValid of [true, false, null] as const) {
      const r = classifyRecoveryAction({ statusText, snapshotValid });
      assert.equal(r.actionable, false, `snapshotValid=${snapshotValid}`);
      assert.equal(r.actionLabel, null);
      assert.ok(r.explanation && /deliberate recovery/i.test(r.explanation));
    }
  });
}

for (const statusText of [
  "START FAILED - could not capture complete inverter snapshot",
  "START FAILED - could not durably commit the recovery snapshot; nothing written",
]) {
  test(`Rule E: "${statusText}" + no snapshot -> no actionable button`, () => {
    const r = classifyRecoveryAction({ statusText, snapshotValid: false });
    assert.equal(r.actionable, false);
    assert.equal(r.actionLabel, null);
    assert.ok(r.explanation && /no saved snapshot/i.test(r.explanation));
  });
}

test("Rule E does not fire when a snapshot IS held (mid-activation failure, not pre-snapshot)", () => {
  const r = classifyRecoveryAction({
    statusText: "ACTIVATION VERIFY FAILED - restoring saved snapshot",
    snapshotValid: true,
  });
  assert.equal(r.actionable, true);
  assert.equal(r.actionLabel, "End & Restore Now");
});

test("Rule D takes priority over Rule A/B even if the text also happens to match them", () => {
  const r = classifyRecoveryAction({
    statusText: "RECOVERY BLOCKED and RECOVERY REQUIRED at once (hypothetical)",
    snapshotValid: true,
  });
  assert.equal(r.actionable, false);
});

// Rule F: "RESTORE BLOCKED - ..." is a live three-way state mismatch that
// needs an operator's own judgement call, not a routine one-click retry -
// it must never present as the same inviting, dominant action as the other
// rules, and must offer nothing at all when there's no confirmed snapshot
// to restore in the first place.
const RESTORE_BLOCKED_TEXT =
  "RESTORE BLOCKED - live inverter state matches neither the saved snapshot nor Free Power's intended state; operator decision required";

test("Rule F: RESTORE BLOCKED + valid snapshot -> secondary Attempt Restore, not the dominant CTA", () => {
  const r = classifyRecoveryAction({ statusText: RESTORE_BLOCKED_TEXT, snapshotValid: true });
  assert.equal(r.actionable, true);
  assert.notEqual(r.actionLabel, "End & Restore Now");
  assert.equal(r.actionLabel, "Attempt Restore");
  assert.equal(r.secondary, true);
  assert.ok(r.explanation && /operator decision/i.test(r.explanation));
  assert.ok(r.explanation && /not guaranteed/i.test(r.explanation));
});

test("Rule F: RESTORE BLOCKED + no confirmed snapshot (false) -> no actionable button", () => {
  const r = classifyRecoveryAction({ statusText: RESTORE_BLOCKED_TEXT, snapshotValid: false });
  assert.equal(r.actionable, false);
  assert.equal(r.actionLabel, null);
  assert.ok(r.explanation && /operator decision/i.test(r.explanation));
});

test("Rule F: RESTORE BLOCKED + unknown snapshot state (null) -> no actionable button", () => {
  const r = classifyRecoveryAction({ statusText: RESTORE_BLOCKED_TEXT, snapshotValid: null });
  assert.equal(r.actionable, false);
  assert.equal(r.actionLabel, null);
});

test("unrecognised recovery text with a CONFIRMED snapshot still falls back to the plain dominant End & Restore Now", () => {
  const r = classifyRecoveryAction({
    statusText: "SOME FUTURE FIRMWARE STATUS NOT YET MAPPED TO ANY RULE",
    snapshotValid: true,
  });
  assert.equal(r.actionable, true);
  assert.equal(r.actionLabel, "End & Restore Now");
  assert.equal(r.secondary, false);
});

test("fail-closed: unrecognised recovery text with snapshot_valid unknown (null) offers no restore action", () => {
  const r = classifyRecoveryAction({
    statusText: "SOME FUTURE FIRMWARE STATUS NOT YET MAPPED TO ANY RULE",
    snapshotValid: null,
  });
  assert.equal(r.actionable, false);
  assert.equal(r.actionLabel, null);
  assert.ok(r.explanation);
});

test("fail-closed: unrecognised recovery text with snapshot_valid false offers no restore action", () => {
  const r = classifyRecoveryAction({
    statusText: "SOME FUTURE FIRMWARE STATUS NOT YET MAPPED TO ANY RULE",
    snapshotValid: false,
  });
  assert.equal(r.actionable, false);
  assert.equal(r.actionLabel, null);
});
