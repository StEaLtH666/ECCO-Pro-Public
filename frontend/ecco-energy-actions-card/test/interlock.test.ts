import { test } from "node:test";
import assert from "node:assert/strict";
import {
  siblingOwnsInverter,
  isInterlocked,
  canActWhileInterlocked,
  interlockMessage,
} from "../src/interlock.ts";

// ---------------------------------------------------------------------
// siblingOwnsInverter() - the raw "does the sibling currently have a live
// inverter ownership/recovery obligation" check.
// ---------------------------------------------------------------------

test("siblingOwnsInverter is false for ready/armed and for null (not configured/unavailable)", () => {
  assert.equal(siblingOwnsInverter("ready"), false);
  assert.equal(siblingOwnsInverter("armed"), false);
  assert.equal(siblingOwnsInverter(null), false);
});

test("siblingOwnsInverter is true for active/busy/recovery_attention/deferred", () => {
  assert.equal(siblingOwnsInverter("active"), true);
  assert.equal(siblingOwnsInverter("busy"), true);
  assert.equal(siblingOwnsInverter("recovery_attention"), true);
  assert.equal(siblingOwnsInverter("deferred"), true);
});

// ---------------------------------------------------------------------
// isInterlocked() - the full state-priority rule combining own state with
// sibling ownership. Test numbers below refer to the task's own list.
// ---------------------------------------------------------------------

test("1. both ready => neither is interlocked", () => {
  assert.equal(isInterlocked("ready", "ready"), false);
});

test("2. Dump ACTIVE => Free Power (ready or armed) is interlocked", () => {
  assert.equal(isInterlocked("ready", "active"), true);
  assert.equal(isInterlocked("armed", "active"), true);
});

test("3. Free Power ACTIVE => Dump (ready or armed) is interlocked", () => {
  // Same function, called from the Dump tile's perspective (own=Dump's state, sibling=Free Power's state).
  assert.equal(isInterlocked("ready", "active"), true);
  assert.equal(isInterlocked("armed", "active"), true);
});

test("4. sibling RESTORING (busy) => this feature is interlocked", () => {
  assert.equal(isInterlocked("ready", "busy"), true);
  assert.equal(isInterlocked("armed", "busy"), true);
});

test("5. mirrors case 4 symmetrically (same pure function, either direction)", () => {
  assert.equal(isInterlocked("ready", "busy"), true);
});

test("6. sibling recovery obligation (recovery_attention) => this feature is interlocked", () => {
  assert.equal(isInterlocked("ready", "recovery_attention"), true);
  assert.equal(isInterlocked("armed", "recovery_attention"), true);
});

test("7. sibling durable snapshot/restore obligation (deferred) => this feature is interlocked", () => {
  assert.equal(isInterlocked("ready", "deferred"), true);
  assert.equal(isInterlocked("armed", "deferred"), true);
});

test("8. sibling merely SCHEDULED (still visualState ready) => NOT interlocked", () => {
  // A confirmed schedule only ever overlays the display state on top of the
  // plain "ready" visualState (see resolveDisplayState()/
  // resolveDumpDisplayState()) - isInterlocked() must be called with that
  // underlying visualState, never the "scheduled" display state, so this
  // case is indistinguishable from plain "ready" here by construction.
  assert.equal(isInterlocked("ready", "ready"), false);
});

test("9. mirrors case 8 symmetrically (same pure function, either direction)", () => {
  assert.equal(isInterlocked("ready", "ready"), false);
});

test("10. own recovery_attention outranks sibling interlock", () => {
  assert.equal(isInterlocked("recovery_attention", "active"), false);
  assert.equal(isInterlocked("recovery_attention", "busy"), false);
});

test("11. own active outranks sibling interlock", () => {
  assert.equal(isInterlocked("active", "active"), false);
  assert.equal(isInterlocked("active", "recovery_attention"), false);
});

test("own busy/deferred/unavailable also outrank sibling interlock (only ready/armed can ever become interlocked)", () => {
  for (const own of ["busy", "deferred", "unavailable"] as const) {
    assert.equal(isInterlocked(own, "active"), false, `expected own=${own} to outrank sibling interlock`);
  }
});

test("null sibling (sibling feature not configured/unavailable) never interlocks", () => {
  assert.equal(isInterlocked("ready", null), false);
  assert.equal(isInterlocked("armed", null), false);
});

// ---------------------------------------------------------------------
// 12. controls disabled appropriately while interlocked
// ---------------------------------------------------------------------

test("12. canActWhileInterlocked gates an otherwise-allowed control off while interlocked, and never re-enables one already disallowed", () => {
  assert.equal(canActWhileInterlocked(true, true), false);
  assert.equal(canActWhileInterlocked(true, false), true);
  assert.equal(canActWhileInterlocked(false, true), false);
  assert.equal(canActWhileInterlocked(false, false), false);
});

// ---------------------------------------------------------------------
// interlockMessage() - concise, non-alarming wording, never implying a
// fault with THIS feature.
// ---------------------------------------------------------------------

test("interlockMessage names live ownership for an active sibling", () => {
  assert.equal(interlockMessage("Dump to Grid", "active"), "Dump to Grid currently owns inverter control.");
});

test("interlockMessage names restoring for a busy sibling", () => {
  assert.equal(interlockMessage("Free Power", "busy"), "Free Power is restoring inverter state.");
});

test("interlockMessage names a recovery obligation for recovery_attention or deferred", () => {
  assert.equal(
    interlockMessage("Dump to Grid", "recovery_attention"),
    "Dump to Grid requires recovery before this can be used."
  );
  assert.equal(
    interlockMessage("Dump to Grid", "deferred"),
    "Dump to Grid requires recovery before this can be used."
  );
});
