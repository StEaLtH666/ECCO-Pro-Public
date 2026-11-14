import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildPlanSnapshot, readTouTable } from "../src/plan/adapter.ts";
import type { FieldInfo } from "../src/plan/adapter.ts";
import { BASE_CONFIG, P } from "./support/fixtures.ts";
import { ADVICE, PLAN_CONFIG, TABLE, planConfig, planStates, slotEntity, withTable } from "./support/planFixtures.ts";

const field = (fields: FieldInfo[], path: string): FieldInfo => {
  const f = fields.find((x) => x.path === path);
  assert.ok(f, path);
  return f;
};
const D = BASE_CONFIG.dump_to_grid;
const SD = BASE_CONFIG.dump_to_grid.schedule;
const FP = BASE_CONFIG.free_power;
const SF = BASE_CONFIG.schedule;

test("idle: every readable field is PROPOSED, nothing is verified, the table is unchanged and verified slot by slot", () => {
  const snap = buildPlanSnapshot(planConfig() as never, planStates());
  for (const f of snap.fields) assert.notEqual(f.state === "APPLIED_VERIFIED" && f.path !== "charge.targetSoc", true, f.path);
  assert.equal(field(snap.fields, "charge.powerW").state, "PROPOSED");
  assert.equal(field(snap.fields, "export.stopSoc").value, 25);
  assert.equal(snap.tou.readable, true);
  assert.equal(snap.tou.compile?.status, "OK");
  assert.equal(snap.tou.compile?.fallback, true);
  assert.ok(snap.tou.compile?.slotReports.every((r) => r.state === "APPLIED_VERIFIED" && r.origin === "native-fallback"));
  assert.deepEqual(snap.overrides, []);
});

test("fields without any entity are unknown with a reason, never a number", () => {
  const snap = buildPlanSnapshot(planConfig() as never, planStates());
  for (const p of ["charge.bufferMin", "reserve.planningPct"]) {
    const f = field(snap.fields, p);
    assert.equal(f.known, false);
    assert.ok(f.reason && f.reason.length > 10);
  }
  const noReserve = buildPlanSnapshot(planConfig({}, { reserve: undefined }) as never, planStates());
  assert.equal(field(noReserve.fields, "reserve.backupPct").known, false);
  assert.equal(noReserve.tomorrow.reservePct.known, false);
  assert.ok(!noReserve.tomorrow.why.some((w) => w.text.startsWith("Backup reserve ")));
  assert.ok(noReserve.tomorrow.why.some((w) => w.text.startsWith("Backup reserve: unknown")));
});

test("the charge target comes from the single native grid-charge slot and is verified by it; two grid slots make it unknown", () => {
  const snap = buildPlanSnapshot(planConfig() as never, planStates());
  const t = field(snap.fields, "charge.targetSoc");
  assert.equal(t.value, 80);
  assert.equal(t.observed, 80);
  assert.equal(t.state, "APPLIED_VERIFIED");
  const two = withTable(planStates(), TABLE.map((s, i) => (i === 3 ? { ...s, charge: "Grid" as const } : s)));
  const snap2 = buildPlanSnapshot(planConfig() as never, two);
  assert.equal(field(snap2.fields, "charge.targetSoc").known, false);
});

test("an Intelligence charge target that differs is only a proposal; the value does not change", () => {
  const snap = buildPlanSnapshot(planConfig() as never, planStates(true, { target: 90 }));
  const t = field(snap.fields, "charge.targetSoc");
  assert.equal(t.value, 80);
  assert.equal(t.proposal, 90);
  assert.equal(snap.settings.fields["charge.targetSoc"].source, "owner");
  const same = buildPlanSnapshot(planConfig() as never, planStates(true, { target: 80 }));
  assert.equal(field(same.fields, "charge.targetSoc").proposal, null);
});

test("all five states are reachable and each only when its evidence is present", () => {
  const states = planStates();
  // ARMED: the dump schedule is armed.
  states[SD.armed] = { state: "on" };
  let snap = buildPlanSnapshot(planConfig() as never, states);
  assert.equal(field(snap.fields, "export.stopSoc").state, "ARMED");
  assert.equal(field(snap.fields, "export.powerW").state, "ARMED");
  assert.equal(field(snap.fields, "charge.powerW").state, "PROPOSED");
  // EXECUTING: the session is active and no latched read-back exists yet.
  states[D.active] = { state: "on" };
  snap = buildPlanSnapshot(planConfig() as never, states);
  assert.equal(field(snap.fields, "export.stopSoc").state, "EXECUTING");
  assert.equal(field(snap.fields, "export.startMin").state, "EXECUTING");
  // APPLIED_VERIFIED: the firmware's latched values equal the intended ones.
  const withLatch = { ...BASE_CONFIG, show_plan: true, plan: PLAN_CONFIG, dump_to_grid: { ...D, active_export_power: "sensor.test_latched_power", active_stop_soc: "sensor.test_latched_stop" } };
  states["sensor.test_latched_power"] = { state: "2000" };
  states["sensor.test_latched_stop"] = { state: "25" };
  snap = buildPlanSnapshot(withLatch as never, states);
  assert.equal(field(snap.fields, "export.powerW").state, "APPLIED_VERIFIED");
  assert.equal(field(snap.fields, "export.stopSoc").state, "APPLIED_VERIFIED");
  assert.equal(field(snap.fields, "export.durationMin").state, "EXECUTING", "no read-back, so not claimed verified");
  // MISMATCH: the latched value differs from the intended one.
  states["sensor.test_latched_stop"] = { state: "40" };
  snap = buildPlanSnapshot(withLatch as never, states);
  const stop = field(snap.fields, "export.stopSoc");
  assert.equal(stop.state, "MISMATCH");
  assert.equal(stop.observed, 40);
  // An unreadable read-back never verifies.
  states["sensor.test_latched_stop"] = { state: "unavailable" };
  snap = buildPlanSnapshot(withLatch as never, states);
  assert.equal(field(snap.fields, "export.stopSoc").state, "EXECUTING");
});

test("a Free Power schedule arms the charge fields; an active session executes them", () => {
  const states = planStates();
  states[SF.armed] = { state: "on" };
  let snap = buildPlanSnapshot(planConfig() as never, states);
  assert.equal(field(snap.fields, "charge.windowStartMin").value, 120);
  assert.equal(field(snap.fields, "charge.windowEndMin").value, 210);
  assert.equal(field(snap.fields, "charge.windowStartMin").state, "ARMED");
  states[FP.active] = { state: "on" };
  snap = buildPlanSnapshot(planConfig() as never, states);
  assert.equal(field(snap.fields, "charge.powerW").state, "EXECUTING");
});

test("a value outside what ECCO accepts is unknown with the reason, not clamped or shown", () => {
  const states = planStates();
  states[SD.power] = { state: "9000" };
  states[SD.stop_soc] = { state: "5" };
  const snap = buildPlanSnapshot(planConfig() as never, states);
  const p = field(snap.fields, "export.powerW");
  assert.equal(p.known, false);
  assert.match(p.reason ?? "", /outside what ECCO accepts/);
  const s = field(snap.fields, "export.stopSoc");
  assert.equal(s.known, false);
  assert.match(s.reason ?? "", /refused, not clamped/);
});

test("Tomorrow's Plan: advice becomes PROPOSED figures, the finish time stays unknown, the import caveat is stated", () => {
  const snap = buildPlanSnapshot(planConfig() as never, planStates());
  const t = snap.tomorrow;
  assert.equal(snap.adviceAvailable, true);
  assert.deepEqual([t.importKwh.known && t.importKwh.value, t.exportKwh.known && t.exportKwh.value, t.solarKwh.known && t.solarKwh.value], [4.5, 2.2, 11.4]);
  for (const i of [t.importKwh, t.exportKwh, t.solarKwh]) assert.equal(i.state, "PROPOSED");
  assert.equal(t.confidence.level, "HIGH");
  assert.equal(t.chargeFinishMin.known, false);
  assert.ok(t.why.some((w) => /grid energy Intelligence plans for the overnight charge/.test(w.text)));
  assert.equal(t.reservePct.known && t.reservePct.value, 20);
});

test("Tomorrow's Plan: missing inputs are explicit unknowns, not zeros", () => {
  const snap = buildPlanSnapshot(planConfig() as never, planStates(true, { importKwh: null, solarKwh: null, exportKwh: null }));
  assert.equal(snap.tomorrow.importKwh.known, false);
  assert.equal(snap.tomorrow.solarKwh.known, false);
  assert.equal(snap.tomorrow.exportKwh.known, false);
});

test("Tomorrow's Plan: a missing, paused, stale or not-OK advice withholds every figure with its reason", () => {
  const none = buildPlanSnapshot(planConfig() as never, planStates(false));
  assert.equal(none.adviceAvailable, false);
  assert.match(none.adviceNote ?? "", /not available/);
  assert.equal(none.tomorrow.confidence.known, false);
  for (const [opts, re] of [
    [{ paused: true }, /paused/],
    [{ fresh: false }, /not fresh/],
    [{ status: "NO_ADVICE" }, /NO_ADVICE/],
  ] as const) {
    const s = buildPlanSnapshot(planConfig() as never, planStates(true, opts));
    assert.equal(s.adviceAvailable, false);
    assert.equal(s.tomorrow.importKwh.known, false);
    assert.equal(s.tomorrow.solarKwh.known, false);
    const reason = s.tomorrow.solarKwh.known ? "" : s.tomorrow.solarKwh.reason;
    assert.match(reason, re);
  }
});

test("an unreadable TOU slot makes the whole table unreadable: no comparison, no compile", () => {
  const states = planStates();
  states[slotEntity(3, "power")] = { state: "unavailable" };
  const snap = buildPlanSnapshot(planConfig() as never, states);
  assert.equal(snap.tou.readable, false);
  assert.match(snap.tou.reason ?? "", /slot 3 power/);
  assert.equal(snap.tou.compile, null);
  const noPrefix = buildPlanSnapshot(planConfig({}, { entity_prefix: undefined }) as never, planStates());
  assert.equal(noPrefix.tou.readable, false);
  assert.match(noPrefix.tou.reason ?? "", /No TOU slot prefix/);
});

test("readTouTable rejects an invalid cycle and a slot with an unknown charge source", () => {
  const bad = withTable({}, TABLE.map((t, i) => (i === 2 ? { ...t, start: "01:00" } : t)));
  assert.match(readTouTable(bad, P).reason ?? "", /valid six-slot day/);
  const odd = withTable({}, TABLE);
  odd[slotEntity(2, "charge")] = { state: "Battery" };
  assert.match(readTouTable(odd, P).reason ?? "", /slot 2 charge source/);
});

test("an armed charge changes the intended table; the slots that differ from the inverter are MISMATCH with the table otherwise intact", () => {
  const states = planStates();
  states[SF.armed] = { state: "on" };
  states[SF.start] = { state: "2026-11-15 02:00:00" };
  states[SF.duration] = { state: "180" };
  const snap = buildPlanSnapshot(planConfig() as never, states);
  const c = snap.tou.compile;
  assert.ok(c);
  assert.equal(c.status, "OK");
  assert.equal(c.slots.length, 6);
  assert.ok(c.slotReports.some((r) => r.state === "MISMATCH"), "intended differs from the inverter");
  assert.ok(c.slotReports.some((r) => r.origin === "derived:charge"));
  assert.ok(c.edits.length > 0);
});

test("an armed export is not placed in the table without an explicit unlocked lock (fail-safe), and is placed with one", () => {
  const states = planStates();
  states[SD.armed] = { state: "on" };
  states[SD.start] = { state: "2026-11-15 17:00:00" };
  const noLock = buildPlanSnapshot(planConfig({}, { control_lock: undefined }) as never, states);
  assert.ok(noLock.tou.notes.some((n) => /No grid-loss lock state is configured/.test(n)));
  assert.ok(noLock.tou.compile?.refused.some((r) => r.action === "export"));
  const locked = planStates();
  locked[SD.armed] = { state: "on" };
  locked[PLAN_CONFIG.control_lock] = { state: "on" };
  assert.ok(buildPlanSnapshot(planConfig() as never, locked).tou.compile?.refused.some((r) => r.action === "export"));
  const unreadable = planStates();
  unreadable[SD.armed] = { state: "on" };
  unreadable[PLAN_CONFIG.control_lock] = { state: "unavailable" };
  assert.ok(buildPlanSnapshot(planConfig() as never, unreadable).tou.compile?.refused.some((r) => r.action === "export"));
  const open = buildPlanSnapshot(planConfig() as never, states);
  assert.equal(open.tou.compile?.refused.length, 0);
  assert.ok(open.tou.compile?.intervals.some((i) => i.action === "export"));
});

test("a plan that needs more than six slots is INFEASIBLE with its reason and the native table is left as it is", () => {
  const spread = [
    { start: "00:00", power: 3000, soc: 20, charge: "None" as const },
    { start: "04:00", power: 5000, soc: 80, charge: "Grid" as const },
    { start: "08:00", power: 4000, soc: 30, charge: "None" as const },
    { start: "12:00", power: 3500, soc: 25, charge: "None" as const },
    { start: "16:00", power: 3200, soc: 35, charge: "None" as const },
    { start: "20:00", power: 2800, soc: 40, charge: "None" as const },
  ];
  const states = withTable(planStates(), spread);
  states[SF.armed] = { state: "on" };
  states[SF.start] = { state: "2026-11-15 02:00:00" };
  states[SF.duration] = { state: "90" };
  const snap = buildPlanSnapshot(planConfig() as never, states);
  const c = snap.tou.compile;
  assert.equal(c?.status, "INFEASIBLE");
  assert.match(c?.reasons[0] ?? "", /Six native slots are not enough/);
  assert.equal(c?.fallback, true);
  assert.deepEqual(c?.slots.map((s) => s.startMin), spread.map((s) => Number(s.start.slice(0, 2)) * 60));
});

test("while a Free Power or Dump session owns the inverter nothing is compiled (single writer)", () => {
  const states = planStates();
  states[`binary_sensor.${P}_dump_to_grid_snapshot_valid`] = { state: "on" };
  const snap = buildPlanSnapshot(planConfig() as never, states);
  assert.equal(snap.tou.compile?.status, "REFUSED");
  assert.match(snap.tou.compile?.reasons[0] ?? "", /Single writer: Dump to Grid/);
});

test("the adapter is read only and pure: it imports only the plan core and types, and names no service call, clock or storage", () => {
  const src = readFileSync(new URL("../src/plan/adapter.ts", import.meta.url), "utf8");
  const imports = [...src.matchAll(/^import[^;]*?from\s+"([^"]+)";/gms)].map((m) => m[1]);
  assert.deepEqual([...new Set(imports)].sort(), ["../../../ecco-plan-core/src/index.ts", "../config"]);
  for (const bad of [/callService/, /hass/, /Date/, /localStorage/, /fetch/, /document/, /window/, /innerHTML/, /from "lit/, /Math.random/]) {
    assert.ok(!bad.test(src), "adapter must not contain " + bad);
  }
});

test("the adapter does not change its input", () => {
  const states = planStates();
  const before = JSON.stringify(states);
  const cfg = planConfig();
  const cfgBefore = JSON.stringify(cfg);
  buildPlanSnapshot(cfg as never, states);
  assert.equal(JSON.stringify(states), before);
  assert.equal(JSON.stringify(cfg), cfgBefore);
  assert.ok(ADVICE.status);
});
