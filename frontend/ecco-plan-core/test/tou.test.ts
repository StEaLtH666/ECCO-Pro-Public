import { test } from "node:test";
import assert from "node:assert/strict";
import { compileTou, validateTable, sameTable } from "../src/tou.ts";
import type { CompileInput, DerivedInterval, NativeSlot } from "../src/tou.ts";
import { compileInvariantViolations } from "../src/guards.ts";
import { elapsedMinutes } from "../src/time.ts";
import type { ClockDay } from "../src/time.ts";
import { distinctBaseline, exampleBaseline, quietBaseline, rng, slot } from "./fixtures.ts";

const charge = (startMin: number, durationMin: number, powerW = 3200, targetSoc = 90): DerivedInterval => ({ action: "charge", startMin, durationMin, powerW, targetSoc });
const exp = (startMin: number, durationMin: number, powerW = 3000, targetSoc = 30): DerivedInterval => ({ action: "export", startMin, durationMin, powerW, targetSoc });
const input = (baseline: NativeSlot[], intervals: DerivedInterval[], extra: Partial<CompileInput> = {}): CompileInput => ({ baseline, intervals, controlLocked: false, ...extra });
const SPRING: ClockDay = { changeAtMin: 120, deltaMin: 60 };
const AUTUMN: ClockDay = { changeAtMin: 180, deltaMin: -60 };

test("no derived intervals: the native baseline is returned unchanged (explicit fallback), including merged-looking slots", () => {
  for (const b of [exampleBaseline(), quietBaseline(), distinctBaseline()]) {
    const r = compileTou(input(b, []));
    assert.equal(r.status, "OK");
    assert.equal(r.fallback, true);
    assert.deepEqual(r.slots, b);
    assert.deepEqual(r.edits, []);
    assert.ok(r.slotReports.every((s) => s.origin === "native-fallback"));
  }
});

test("a charge window over the baseline's own grid slot edits only that slot's power (single-field edit), across midnight", () => {
  const r = compileTou(input(exampleBaseline(), [charge(23 * 60 + 30, 330)]));
  assert.equal(r.status, "OK");
  assert.deepEqual(r.edits, [{ slot: 1, field: "powerW", from: 5000, to: 3200 }]);
  assert.equal(r.slotReports[0]?.origin, "derived:charge");
  assert.equal(r.slotReports[1]?.origin, "native-fallback");
  assert.deepEqual(r.intervals, [{ action: "charge", startMin: 1410, wallMin: 330, elapsedMin: 330 }]);
});

test("an export on top of merged idle slots compiles into six slots, keeping other slot numbers stable", () => {
  const r = compileTou(input(exampleBaseline(), [exp(19 * 60 + 30, 150)]));
  assert.equal(r.status, "OK");
  assert.equal(r.slots.length, 6);
  const e = r.slotReports.find((s) => s.origin === "derived:export");
  assert.ok(e);
  assert.deepEqual([e.intended.startMin, e.intended.powerW, e.intended.targetSoc, e.intended.source], [1170, 3000, 30, "None"]);
  assert.deepEqual(r.slots.slice(0, 4), exampleBaseline().slice(0, 4), "slots 1-4 are untouched");
  assert.equal(validateTable(r.slots).ok, true);
});

test("an export that wraps midnight on a quiet table", () => {
  const r = compileTou(input(quietBaseline(), [exp(23 * 60, 120)]));
  assert.equal(r.status, "OK");
  const starts = r.slots.map((s) => s.startMin).sort((a, b) => a - b);
  assert.ok(starts.includes(1380) && starts.includes(60));
  assert.equal(r.slotsNeeded, 2);
  assert.equal(compileInvariantViolations(r).length, 0);
});

test("needing more than six slots is an explicit INFEASIBLE with a reason; the native table stays as it is", () => {
  const b = distinctBaseline();
  const r = compileTou(input(b, [exp(1000, 100)]));
  assert.equal(r.status, "INFEASIBLE");
  assert.match(r.reasons[0] as string, /needs 8 distinct slots/);
  assert.match(r.reasons[0] as string, /exactly 6/);
  assert.equal(r.slotsNeeded, 8);
  assert.deepEqual(r.slots, b);
  assert.equal(r.fallback, true);
  assert.deepEqual(r.edits, []);
});

test("five-minute grid: off-grid starts and durations are refused", () => {
  assert.equal(compileTou(input(quietBaseline(), [exp(1202, 60)])).status, "REFUSED");
  assert.equal(compileTou(input(quietBaseline(), [exp(1200, 62)])).status, "REFUSED");
  assert.equal(compileTou(input(quietBaseline(), [exp(1200, 0)])).status, "REFUSED");
  assert.equal(compileTou(input(quietBaseline(), [exp(1200, 5, 3000, 30)])).status, "OK", "a 5-minute interval is the smallest allowed");
});

test("export Stop SOC outside 10-90 and power above the tested ceiling are refused at the compiler too", () => {
  for (const soc of [0, 5, 9, 91]) assert.equal(compileTou(input(quietBaseline(), [exp(1200, 60, 3000, soc)])).status, "REFUSED", "soc " + soc);
  assert.equal(compileTou(input(quietBaseline(), [exp(1200, 60, 3500, 30)])).status, "REFUSED");
});

test("merging: identical neighbours collapse, so a plan that looks like many slots can still fit", () => {
  const r = compileTou(input(quietBaseline(), [exp(300, 120)]));
  assert.equal(r.status, "OK");
  assert.equal(r.slotsNeeded, 2);
  assert.equal(r.slots.length, 6);
});

test("export may not overlap, touch or crowd the charge window", () => {
  const b = exampleBaseline();
  assert.match(compileTou(input(b, [charge(1410, 330), exp(1380, 60)])).reasons[0] as string, /overlap/);
  assert.equal(compileTou(input(b, [charge(1410, 330), exp(1350, 60)])).status, "REFUSED", "ends exactly at the charge start: the end minute counts");
  assert.equal(compileTou(input(b, [charge(1410, 330), exp(1170, 150)])).status, "OK", "a 90-minute handover is enough by default");
  assert.equal(compileTou(input(b, [charge(1410, 330), exp(1170, 150)], { handoverGapMin: 100 })).status, "REFUSED");
  assert.equal(compileTou(input(b, [charge(1410, 330), exp(1170, 150)], { handoverGapMin: 90 })).status, "OK");
});

test("DST: elapsed minutes follow the real day (23 and 25 hours); derived changes in the 00:00-03:00 hours wait", () => {
  assert.equal(elapsedMinutes(1410, 330, SPRING), 270);
  assert.equal(elapsedMinutes(1410, 330, AUTUMN), 390);
  assert.equal(elapsedMinutes(1410, 330, { changeAtMin: 0, deltaMin: 0 }), 330);
  assert.equal(elapsedMinutes(1200, 120, SPRING), 120, "an interval that does not cross the change is unchanged");
  const spring = compileTou(input(exampleBaseline(), [charge(1410, 330)], { day: SPRING }));
  assert.equal(spring.status, "OK");
  assert.equal(spring.intervals[0]?.elapsedMin, 270);
  const autumn = compileTou(input(exampleBaseline(), [charge(1410, 330)], { day: AUTUMN }));
  assert.equal(autumn.intervals[0]?.elapsedMin, 390);
  const night = compileTou(input(quietBaseline(), [exp(30, 120)], { day: SPRING }));
  assert.equal(night.status, "REFUSED");
  assert.equal(night.deferredToAfterClockChange, true);
  assert.equal(compileTou(input(quietBaseline(), [exp(30, 120)])).status, "OK", "the same export on an ordinary night");
  assert.equal(compileTou(input(exampleBaseline(), [charge(120, 120, 3200, 90)], { day: AUTUMN })).deferredToAfterClockChange, true);
});

test("manual TOU edit: an observed table that differs from the baseline or from what ECCO last applied is a CONFLICT, never overwritten", () => {
  const b = exampleBaseline();
  const edited = b.map((s) => ({ ...s }));
  (edited[2] as NativeSlot).targetSoc = 25;
  const c1 = compileTou(input(b, [charge(1410, 330)], { observed: edited }));
  assert.equal(c1.status, "CONFLICT");
  assert.deepEqual(c1.edits, [], "no restoring edit is proposed over someone's change");
  assert.deepEqual(c1.slots, b);
  assert.equal(c1.slotReports[2]?.state, "MISMATCH");

  const first = compileTou(input(b, [charge(1410, 330)], { observed: b }));
  assert.equal(first.status, "OK");
  assert.equal(first.slotReports[0]?.state, "MISMATCH", "intended differs from what is on the inverter: not verified");
  assert.equal(first.slotReports[1]?.state, "APPLIED_VERIFIED");
  const applied = first.slots;
  const settled = compileTou(input(b, [charge(1410, 330)], { observed: applied, lastApplied: applied }));
  assert.equal(settled.status, "OK");
  assert.ok(settled.slotReports.every((s) => s.state === "APPLIED_VERIFIED"));
  assert.deepEqual(settled.edits, []);
  const tampered = applied.map((s) => ({ ...s }));
  (tampered[0] as NativeSlot).powerW = 4000;
  assert.equal(compileTou(input(b, [charge(1410, 330)], { observed: tampered, lastApplied: applied })).status, "CONFLICT");
  assert.equal(compileTou(input(b, [], { observed: [slot(0, 1, 1, "None")] })).status, "CONFLICT", "an unreadable observed table");
});

test("single writer: a transaction owner refuses the compile", () => {
  const r = compileTou(input(exampleBaseline(), [charge(1410, 330)], { transactionOwner: "export_to_grid" }));
  assert.equal(r.status, "REFUSED");
  assert.match(r.reasons[0] as string, /Single writer/);
  assert.equal(r.fallback, true);
});

test("control lock: every export start is refused (fail-safe), charging still compiles", () => {
  const b = exampleBaseline();
  for (const locked of [true, undefined, "no" as unknown as boolean]) {
    const r = compileTou({ baseline: b, intervals: [charge(1410, 330), exp(1170, 150)], controlLocked: locked as boolean });
    assert.equal(r.status, "OK");
    assert.equal(r.refused.length, 1);
    assert.equal(r.refused[0]?.action, "export");
    assert.ok(!r.slotReports.some((s) => s.origin === "derived:export"));
    assert.deepEqual(r.edits, [{ slot: 1, field: "powerW", from: 5000, to: 3200 }]);
  }
});

test("an invalid baseline is refused rather than repaired", () => {
  const bad = exampleBaseline();
  bad.pop();
  assert.equal(compileTou(input(bad, [])).status, "REFUSED");
  assert.equal(validateTable(bad).ok, false);
  const offGrid = exampleBaseline();
  (offGrid[1] as NativeSlot).startMin = 302;
  assert.equal(validateTable(offGrid).ok, false);
  const unordered = exampleBaseline();
  (unordered[2] as NativeSlot).startMin = 200;
  assert.equal(validateTable(unordered).ok, false);
});

test("property: random tables and plans never produce more than six slots or an invalid table; failures fall back to the baseline", () => {
  const rand = rng(61114);
  const seen: Record<string, number> = {};
  const attrs = [
    [5000, 15, "None"],
    [3000, 40, "None"],
    [5000, 90, "Grid"],
    [2000, 60, "Grid"],
  ] as const;
  for (let n = 0; n < 3000; n++) {
    const cells = new Set<number>();
    while (cells.size < 6) cells.add(Math.floor(rand() * 288));
    const starts = [...cells].sort((a, b) => a - b).map((c) => c * 5);
    const rot = Math.floor(rand() * 6);
    const table = starts.map((_, i) => {
      const a = attrs[Math.floor(rand() * (rand() < 0.5 ? 2 : 4))] as (typeof attrs)[number];
      return slot(starts[(i + rot) % 6] as number, a[0], a[1], a[2]);
    });
    assert.equal(validateTable(table).ok, true);
    const intervals: DerivedInterval[] = [];
    if (rand() < 0.7) intervals.push(charge(Math.floor(rand() * 288) * 5 + (rand() < 0.05 ? 2 : 0), (1 + Math.floor(rand() * 100)) * 5, 500 + 100 * Math.floor(rand() * 75), 20 + Math.floor(rand() * 81)));
    if (rand() < 0.7) intervals.push(exp(Math.floor(rand() * 288) * 5, (1 + Math.floor(rand() * 48)) * 5, 500 + 100 * Math.floor(rand() * 26), 5 + Math.floor(rand() * 90)));
    const locked = rand() < 0.3;
    const r = compileTou({ baseline: table, intervals, controlLocked: locked, day: rand() < 0.2 ? SPRING : { changeAtMin: 0, deltaMin: 0 }, transactionOwner: rand() < 0.1 ? "x" : null });
    seen[r.status] = (seen[r.status] ?? 0) + 1;
    assert.deepEqual(compileInvariantViolations(r), [], JSON.stringify({ table, intervals, r }));
    assert.ok(r.slots.length <= 6);
    if (r.status !== "OK") assert.ok(sameTable(r.slots, table), "falls back to the unchanged baseline");
    if (locked) assert.ok(!r.slotReports.some((s) => s.origin === "derived:export"), "no export start under a lock");
  }
  assert.ok((seen["OK"] ?? 0) > 100 && (seen["INFEASIBLE"] ?? 0) > 20 && (seen["REFUSED"] ?? 0) > 20, JSON.stringify(seen));
});
