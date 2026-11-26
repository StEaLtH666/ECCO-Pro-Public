import { test } from "node:test";
import assert from "node:assert/strict";
import { applyOverrides, startOverride, OVERRIDE_KINDS } from "../src/overrides.ts";
import type { ActiveOverride, OverrideKind, OverridePolicy, PlanView, RunningLease } from "../src/overrides.ts";
import { planGentleCharge, SIMULATED_LABEL } from "../src/chargePlanner.ts";
import type { ChargePlanInput } from "../src/chargePlanner.ts";
import { rng } from "./fixtures.ts";

// The documented examples, passed in as owner policy (not defaults baked into the package).
const POLICY: OverridePolicy = {
  minExpiryMin: 15,
  defaultExpiryMin: { hold_battery: 240, skip_tonight: 480, prepare_power_cut: 1440 },
  maxExpiryMin: { hold_battery: 48 * 60, skip_tonight: 600, prepare_power_cut: 72 * 60 },
  powerCutReservePct: 80,
};
const VIEW: PlanView = { startsAllowed: { charge: true, export: true }, discretionaryRateEdits: true, backupReservePct: 50, exportStopSoc: 30 };

test("an override needs a bounded expiry: no open-ended, too short or over-cap override", () => {
  assert.equal(startOverride("hold_battery", 1000, null, POLICY).ok, true, "falls back to the owner's default");
  const noDefault: OverridePolicy = { ...POLICY, defaultExpiryMin: { ...POLICY.defaultExpiryMin, hold_battery: NaN } };
  assert.equal(startOverride("hold_battery", 1000, undefined, noDefault).ok, false);
  assert.equal(startOverride("hold_battery", 1000, 10, POLICY).ok, false);
  assert.equal(startOverride("hold_battery", 1000, 48 * 60 + 1, POLICY).ok, false);
  assert.equal(startOverride("hold_battery", 1000, 48 * 60, POLICY).ok, true);
  assert.equal(startOverride("prepare_power_cut", NaN, 60, POLICY).ok, false);
  const r = startOverride("skip_tonight", 1000, 300, POLICY);
  assert.ok(r.ok && r.override.expiresAtMin === 1300);
  assert.equal(startOverride("prepare_power_cut", 0, 60, { ...POLICY, powerCutReservePct: 5 }).ok, false);
});

test("Hold battery suspends starts of export and discretionary rate edits, nothing else", () => {
  const o = startOverride("hold_battery", 0, 60, POLICY);
  assert.ok(o.ok);
  const out = applyOverrides(VIEW, [o.override], 10);
  assert.equal(out.view.startsAllowed.export, false);
  assert.equal(out.view.startsAllowed.charge, true, "the native charge is untouched");
  assert.equal(out.view.discretionaryRateEdits, false);
  assert.equal(out.view.backupReservePct, 50);
  assert.deepEqual(out.reports[0]?.changes.map((c) => c.field), ["startsAllowed.export", "discretionaryRateEdits"]);
  assert.equal(VIEW.startsAllowed.export, true, "the input view is not mutated");
});

test("Skip tonight holds export only; charging and rate edits continue", () => {
  const o = startOverride("skip_tonight", 0, 300, POLICY);
  assert.ok(o.ok);
  const out = applyOverrides(VIEW, [o.override], 0);
  assert.deepEqual(out.view, { ...VIEW, startsAllowed: { charge: true, export: false } });
  assert.deepEqual(out.reports[0]?.changes, [{ field: "startsAllowed.export", from: true, to: false }]);
});

test("Prepare for power cut raises the reserve (and the export floor with it), never lowers", () => {
  const o = startOverride("prepare_power_cut", 0, 600, POLICY);
  assert.ok(o.ok);
  const up = applyOverrides(VIEW, [o.override], 5);
  assert.equal(up.view.backupReservePct, 80);
  assert.equal(up.view.exportStopSoc, 80);
  assert.equal(up.view.startsAllowed.export, false);
  const already = applyOverrides({ ...VIEW, backupReservePct: 95, exportStopSoc: 95 }, [o.override], 5);
  assert.equal(already.view.backupReservePct, 95);
  assert.equal(already.view.exportStopSoc, 95);
  assert.ok(!already.reports[0]?.changes.some((c) => c.field === "backupReservePct"));
  assert.match(up.reports[0]?.notes.join(" ") as string, /does not prove/);
});

test("an expired override changes nothing and says so", () => {
  const o = startOverride("hold_battery", 0, 60, POLICY);
  assert.ok(o.ok);
  const out = applyOverrides(VIEW, [o.override], 60);
  assert.deepEqual(out.view, VIEW);
  assert.equal(out.reports[0]?.status, "expired");
});

test("a running lease is passed through untouched (same object); the override only affects the next start", () => {
  const lease: RunningLease = { action: "export", startedAt: 5, stopSoc: 30 };
  const before = JSON.stringify(lease);
  const o = startOverride("prepare_power_cut", 0, 600, POLICY);
  assert.ok(o.ok);
  const out = applyOverrides(VIEW, [o.override], 10, lease);
  assert.equal(out.lease, lease);
  assert.equal(JSON.stringify(lease), before);
  assert.match(out.reports[0]?.notes.join(" ") as string, /not stopped or changed/);
});

test("property: no combination of overrides ever lowers a reserve or the export floor", () => {
  const rand = rng(77);
  for (let n = 0; n < 3000; n++) {
    const view: PlanView = { startsAllowed: { charge: rand() < 0.5, export: rand() < 0.5 }, discretionaryRateEdits: rand() < 0.5, backupReservePct: 10 + Math.floor(rand() * 91), exportStopSoc: 10 + Math.floor(rand() * 81) };
    const pol: OverridePolicy = { ...POLICY, powerCutReservePct: 10 + Math.floor(rand() * 91) };
    const active: ActiveOverride[] = [];
    const now = Math.floor(rand() * 100);
    for (const k of OVERRIDE_KINDS) {
      if (rand() < 0.6) {
        const r = startOverride(k as OverrideKind, now - Math.floor(rand() * 30), 15 + Math.floor(rand() * 200), pol);
        if (r.ok) active.push(r.override);
      }
    }
    const out = applyOverrides(view, active, now);
    assert.ok(out.view.backupReservePct >= view.backupReservePct);
    assert.ok(out.view.exportStopSoc >= view.exportStopSoc);
    assert.ok(!(view.startsAllowed.charge === true && out.view.startsAllowed.charge === false), "no override stops charging");
    assert.ok(!(view.startsAllowed.export === false && out.view.startsAllowed.export === true), "no override enables export");
  }
});

// ---- gentle charge planner ----

const base: ChargePlanInput = { startSocPct: 20, targetSocPct: 70, capacityKwh: 30, capacityUpPct: 6, windowMin: 360, bufferMin: 60 };
const near = (a: number | null, b: number, tol = 1) => assert.ok(a !== null && Math.abs(a - b) <= tol, a + " vs " + b);

test("gentle charge: 15 kWh in a 6 h window with a 60 min buffer needs 3200 W; +6 % capacity eats buffer, not window", () => {
  const p = planGentleCharge(base);
  assert.equal(p.status, "OK");
  assert.equal(p.rateW, 3200);
  near(p.finishNominalMin, 296.1);
  near(p.finishStressMin, 313.9);
  near(p.bufferLeftMin, 46.1);
  assert.equal(p.rateFixedAtStart, true);
  assert.equal(p.label, SIMULATED_LABEL);
});

test("buffer too small is reported with a suggestion; the target is never lowered", () => {
  const i: ChargePlanInput = { ...base, bufferMin: 20, taperMin: 30 };
  const p = planGentleCharge(i);
  assert.equal(p.status, "BUFFER_TOO_SMALL");
  assert.equal(p.targetSocPct, 70);
  assert.match(p.reasons[0] as string, /Buffer too small/);
  assert.ok(p.suggestedBufferMin !== null && p.suggestedBufferMin > 20);
  assert.equal(planGentleCharge({ ...i, bufferMin: p.suggestedBufferMin as number }).status, "OK");
  assert.notEqual(planGentleCharge({ ...i, bufferMin: (p.suggestedBufferMin as number) - 5 }).status, "OK");
  const whole = planGentleCharge({ ...base, windowMin: 60, bufferMin: 60 });
  assert.equal(whole.status, "BUFFER_TOO_SMALL");
  assert.equal(whole.rateW, null);
});

test("a window too short for the maximum power is refused, not quietly lowered", () => {
  const p = planGentleCharge({ ...base, startSocPct: 10, targetSocPct: 100, capacityKwh: 40, windowMin: 120, bufferMin: 60, maxW: 6000 });
  assert.equal(p.status, "NEEDS_MORE_POWER");
  assert.equal(p.targetSocPct, 100);
  assert.equal(p.rateW, null);
});

test("nothing to charge, and invalid inputs are named, not guessed", () => {
  assert.equal(planGentleCharge({ ...base, startSocPct: 75 }).status, "NOTHING_TO_CHARGE");
  assert.equal(planGentleCharge({ ...base, bufferMin: 7 }).status, "INVALID");
  assert.equal(planGentleCharge({ ...base, bufferMin: 125 }).status, "INVALID");
  assert.equal(planGentleCharge({ ...base, startSocPct: NaN }).status, "INVALID");
  assert.equal(planGentleCharge({ ...base, capacityKwh: 0 }).status, "INVALID");
  assert.equal(planGentleCharge({ ...base, targetSocPct: 10 }).status, "INVALID");
});

test("property: an OK plan is the lowest 100 W step, finishes in the stress case, and never changes the target", () => {
  const rand = rng(4242);
  let ok = 0;
  for (let n = 0; n < 3000; n++) {
    const i: ChargePlanInput = {
      startSocPct: Math.floor(rand() * 80),
      targetSocPct: 20 + Math.floor(rand() * 81),
      capacityKwh: 5 + rand() * 40,
      capacityUpPct: Math.floor(rand() * 10),
      windowMin: 60 + Math.floor(rand() * 600),
      bufferMin: 5 * Math.floor(rand() * 25),
      taperMin: Math.floor(rand() * 30),
    };
    const p = planGentleCharge(i);
    assert.equal(p.targetSocPct, i.targetSocPct);
    assert.equal(p.label, SIMULATED_LABEL);
    if (p.status !== "OK") continue;
    ok++;
    const rate = p.rateW as number;
    assert.equal(rate % 100, 0);
    const grid = p.gridKwh;
    const t = i.windowMin - i.bufferMin;
    assert.ok((grid / (rate / 1000)) * 60 <= t + 1e-6, "finishes by window end minus buffer");
    assert.ok(rate <= 500 || (grid / ((rate - 100) / 1000)) * 60 > t, "the next step down would not");
    assert.ok((p.finishStressMin as number) <= i.windowMin + 1e-6);
  }
  assert.ok(ok > 200, "enough OK cases exercised: " + ok);
});
