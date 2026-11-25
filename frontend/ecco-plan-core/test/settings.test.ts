import { test } from "node:test";
import assert from "node:assert/strict";
import { createSettings, reduceSettings, parseSettings, serializeSettings, validateField, weakestState, FIELD_PATHS } from "../src/settings.ts";
import type { FieldPath, PlanSettings, SettingsAction } from "../src/settings.ts";
import { appliedClaimIsHonest } from "../src/guards.ts";
import { exampleSettings, exampleValues, rng } from "./fixtures.ts";

const ok = (s: PlanSettings, a: SettingsAction) => {
  const r = reduceSettings(s, a);
  assert.equal(r.ok, true, r.error);
  return r;
};

test("a new field is PROPOSED, never applied, until a matching read-back", () => {
  let s = exampleSettings();
  assert.equal(s.fields["charge.targetSoc"].state, "PROPOSED");
  s = ok(s, { type: "arm", path: "charge.targetSoc" }).settings;
  assert.equal(s.fields["charge.targetSoc"].state, "ARMED");
  s = ok(s, { type: "begin", path: "charge.targetSoc" }).settings;
  assert.equal(s.fields["charge.targetSoc"].state, "EXECUTING");
  s = ok(s, { type: "readback", path: "charge.targetSoc", observed: 85 }).settings;
  assert.equal(s.fields["charge.targetSoc"].state, "MISMATCH");
  s = ok(s, { type: "readback", path: "charge.targetSoc", observed: 90 }).settings;
  assert.equal(s.fields["charge.targetSoc"].state, "APPLIED_VERIFIED");
  assert.ok(appliedClaimIsHonest(s.fields["charge.targetSoc"]));
});

test("owner edits bump a durable revision and go back to PROPOSED", () => {
  let s = exampleSettings();
  s = ok(s, { type: "readback", path: "charge.targetSoc", observed: 90 }).settings;
  assert.equal(s.fields["charge.targetSoc"].state, "APPLIED_VERIFIED");
  const rev = s.revision;
  const r = ok(s, { type: "edit", path: "charge.targetSoc", value: 80, source: "owner" });
  assert.ok(r.settings.revision > rev);
  assert.equal(r.settings.fields["charge.targetSoc"].state, "PROPOSED");
  assert.equal(r.settings.fields["charge.targetSoc"].value, 80);
  assert.equal(s.fields["charge.targetSoc"].value, 90, "the input is not mutated");
});

test("a shared setting propagates to every dependent view at once, as previews", () => {
  const r = ok(exampleSettings(), { type: "edit", path: "export.stopSoc", value: 25, source: "owner" });
  const views = r.updates.map((u) => u.view).sort();
  assert.deepEqual(views, ["export-card", "reserve-summary", "tomorrow-plan", "tou-table"]);
  assert.ok(r.updates.every((u) => u.preview && u.value === 25 && u.state === "PROPOSED"));
  const w = ok(exampleSettings(), { type: "edit", path: "charge.windowStartMin", value: 23 * 60, source: "owner" });
  assert.ok(w.updates.some((u) => u.view === "export-card") && w.updates.some((u) => u.view === "charge-card"));
});

test("an Intelligence proposal never changes the value; only an owner adoption does", () => {
  let s = exampleSettings();
  s = ok(s, { type: "edit", path: "charge.targetSoc", value: 80, source: "intelligence" }).settings;
  assert.equal(s.fields["charge.targetSoc"].value, 90);
  assert.equal(s.fields["charge.targetSoc"].proposal?.value, 80);
  s = ok(s, { type: "adopt-proposal", path: "charge.targetSoc" }).settings;
  assert.equal(s.fields["charge.targetSoc"].value, 80);
  assert.equal(s.fields["charge.targetSoc"].source, "intelligence");
  assert.equal(s.fields["charge.targetSoc"].proposal, null);
});

test("an owner edit overrides a pending proposal; a matching one consumes it", () => {
  let s = exampleSettings();
  s = ok(s, { type: "edit", path: "charge.targetSoc", value: 80, source: "intelligence" }).settings;
  s = ok(s, { type: "edit", path: "charge.targetSoc", value: 70, source: "owner" }).settings;
  assert.equal(s.fields["charge.targetSoc"].value, 70);
  assert.equal(s.fields["charge.targetSoc"].proposal?.value, 80);
  s = ok(s, { type: "edit", path: "charge.targetSoc", value: 80, source: "owner" }).settings;
  assert.equal(s.fields["charge.targetSoc"].proposal, null);
});

test("an external native edit is detected, held and never clobbered", () => {
  let s = exampleSettings();
  s = ok(s, { type: "readback", path: "export.stopSoc", observed: 30 }).settings;
  assert.equal(s.fields["export.stopSoc"].state, "APPLIED_VERIFIED");
  s = ok(s, { type: "readback", path: "export.stopSoc", observed: 55 }).settings;
  const f = s.fields["export.stopSoc"];
  assert.equal(f.value, 30, "intended value is kept");
  assert.equal(f.external?.value, 55);
  assert.equal(f.state, "MISMATCH");
  // the owner cannot silently overwrite, Intelligence cannot either, and nothing can be armed
  assert.equal(reduceSettings(s, { type: "edit", path: "export.stopSoc", value: 40, source: "owner" }).ok, false);
  assert.equal(reduceSettings(s, { type: "edit", path: "export.stopSoc", value: 40, source: "intelligence" }).ok, false);
  assert.equal(reduceSettings(s, { type: "arm", path: "export.stopSoc" }).ok, false);
  const adopt = ok(s, { type: "resolve-external", path: "export.stopSoc", choice: "adopt-native" }).settings.fields["export.stopSoc"];
  assert.equal(adopt.value, 55);
  assert.equal(adopt.source, "native");
  assert.equal(adopt.state, "APPLIED_VERIFIED");
  const keep = ok(s, { type: "resolve-external", path: "export.stopSoc", choice: "keep-intended" }).settings.fields["export.stopSoc"];
  assert.equal(keep.value, 30);
  assert.equal(keep.state, "PROPOSED");
  assert.equal(keep.external, null);
});

test("an unreadable read-back withdraws an applied claim", () => {
  let s = exampleSettings();
  s = ok(s, { type: "readback", path: "reserve.backupPct", observed: 40 }).settings;
  s = ok(s, { type: "readback", path: "reserve.backupPct", observed: null }).settings;
  assert.equal(s.fields["reserve.backupPct"].state, "PROPOSED");
});

test("no edit while a setting is EXECUTING; a stale expected revision is refused", () => {
  let s = exampleSettings();
  s = ok(s, { type: "arm", path: "charge.powerW" }).settings;
  s = ok(s, { type: "begin", path: "charge.powerW" }).settings;
  assert.equal(reduceSettings(s, { type: "edit", path: "charge.powerW", value: 3000, source: "owner" }).ok, false);
  const fresh = exampleSettings();
  const stale = reduceSettings(fresh, { type: "edit", path: "charge.powerW", value: 3000, source: "owner", expectedRevision: fresh.revision - 1 });
  assert.equal(stale.ok, false);
  assert.equal(stale.settings, fresh);
});

test("validation: Stop SOC 10-90 refused not clamped, buffer 0-120 in 5s, times on the 5-minute grid", () => {
  for (const v of [0, 5, 9, 91, 100, 10.5, NaN, Infinity]) assert.equal(validateField("export.stopSoc", v).ok, false, "stop " + v);
  for (const v of [10, 11, 50, 90]) assert.equal(validateField("export.stopSoc", v).ok, true);
  for (const v of [0, 5, 60, 120]) assert.equal(validateField("charge.bufferMin", v).ok, true);
  for (const v of [-5, 3, 125]) assert.equal(validateField("charge.bufferMin", v).ok, false);
  assert.equal(validateField("charge.windowStartMin", 1412).ok, false);
  assert.equal(validateField("charge.windowStartMin", 1410).ok, true);
  assert.equal(validateField("export.powerW", 3100).ok, false, "above the hardware-tested ceiling");
  assert.equal(validateField("export.stopSoc", "30").ok, false);
  assert.equal(validateField("nope", 1).ok, false);
  assert.throws(() => createSettings({ ...exampleValues(), "export.stopSoc": 5 }));
});

test("settings round-trip, and a record claiming verified without a read-back is rejected", () => {
  let s = exampleSettings();
  s = ok(s, { type: "readback", path: "charge.targetSoc", observed: 90 }).settings;
  assert.deepEqual(parseSettings(serializeSettings(s)), s);
  const bad = JSON.parse(serializeSettings(s)) as PlanSettings;
  bad.fields["charge.powerW"].state = "APPLIED_VERIFIED";
  assert.throws(() => parseSettings(JSON.stringify(bad)), /read-back/);
  assert.throws(() => parseSettings("{}"));
});

test("weakestState reports the least verified field", () => {
  let s = exampleSettings();
  for (const p of ["charge.targetSoc", "charge.bufferMin"] as FieldPath[]) s = ok(s, { type: "readback", path: p, observed: s.fields[p].value }).settings;
  assert.equal(weakestState(s, ["charge.targetSoc", "charge.bufferMin"]), "APPLIED_VERIFIED");
  assert.equal(weakestState(s, ["charge.targetSoc", "charge.powerW"]), "PROPOSED");
});

test("property: random action sequences never leave an applied claim without a matching read-back", () => {
  const rand = rng(20261114);
  const paths = FIELD_PATHS;
  let s = exampleSettings();
  let lastRev = s.revision;
  for (let n = 0; n < 4000; n++) {
    const path = paths[Math.floor(rand() * paths.length)] as FieldPath;
    const pick = rand();
    const cur = s.fields[path];
    const vals = [cur.value, cur.observed ?? cur.value, cur.value + 5, 10, 20, 30, 60, 90, 500, 1000, 1410, 300, 5];
    const v = vals[Math.floor(rand() * vals.length)] as number;
    let action: SettingsAction;
    if (pick < 0.2) action = { type: "edit", path, value: v, source: rand() < 0.5 ? "owner" : "intelligence" };
    else if (pick < 0.45) action = { type: "readback", path, observed: rand() < 0.1 ? null : v };
    else if (pick < 0.55) action = { type: "arm", path };
    else if (pick < 0.65) action = { type: "begin", path };
    else if (pick < 0.7) action = { type: "fail", path };
    else if (pick < 0.75) action = { type: "disarm", path };
    else if (pick < 0.85) action = { type: "adopt-proposal", path };
    else if (pick < 0.9) action = { type: "dismiss-proposal", path };
    else action = { type: "resolve-external", path, choice: rand() < 0.5 ? "adopt-native" : "keep-intended" };
    const r = reduceSettings(s, action);
    if (!r.ok) assert.equal(r.settings, s, "a refusal returns the same object");
    s = r.settings;
    assert.ok(s.revision >= lastRev, "revision never goes backwards");
    lastRev = s.revision;
    for (const p of paths) {
      const f = s.fields[p];
      assert.ok(appliedClaimIsHonest(f), p + " " + JSON.stringify(f));
      assert.equal(validateField(p, f.value).ok, true, p + " value stays valid");
      if (f.external) assert.notEqual(f.external.value, f.value);
    }
  }
});
