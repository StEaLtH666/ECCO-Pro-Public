import { test, before } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { PROPOSED_DEFAULTS, applyOverrides } from "../../ecco-plan-core/src/index.ts";
import { buildPlanSnapshot } from "../src/plan/adapter.ts";
import { HELPER_IDS, buildPlanSnapshotWithHelpers, readOverrideHelpers } from "../src/plan/helpers.ts";
import { OVERRIDES_LINE_NONE, OVERRIDES_LINE_NONE_HELPER, presentPlan } from "../src/plan/present.ts";
import { renderPlanSection } from "../src/plan/view.ts";
import { BASE_CONFIG, makeHass } from "./support/fixtures.ts";
import type { States } from "./support/fixtures.ts";
import { flatten, loadCardClass } from "./support/loadCard.ts";
import { FROZEN_NOW, withFrozenClock } from "./support/scenarios.ts";
import { PLAN_ON_SCENARIOS } from "./support/planOnScenarios.ts";
import { MIN, NOW_MIN, NOW_MS, helperStates, running, stamp } from "./support/overrideFixtures.ts";
import { PLAN_CONFIG, planConfig, planStates } from "./support/planFixtures.ts";

const golden = JSON.parse(readFileSync(new URL("./golden/plan-on-render.json", import.meta.url), "utf8")) as Record<string, { sha256: string; length: number }>;
const sha = (t: string): string => createHash("sha256").update(t, "utf8").digest("hex");

const cfg = () => planConfig() as never;
const snapOf = (states: States, nowMin: number | null = NOW_MIN) => buildPlanSnapshotWithHelpers(cfg(), states as never, nowMin);
const vmOf = (states: States, nowMin: number | null = NOW_MIN) => presentPlan(snapOf(states, nowMin));
const configured = (patch: Record<string, unknown> = {}): States => helperStates(planStates(), patch);

let Card: Awaited<ReturnType<typeof loadCardClass>>;
before(async () => {
  Card = await loadCardClass();
});

// ---- nothing configured: exactly as before -----------------------------------------------------------------------------------------

test("no helper entities: the snapshot is the stage-2 snapshot and the plan section is identical to the pre-change golden", () => {
  assert.deepEqual(Object.keys(golden).sort(), Object.keys(PLAN_ON_SCENARIOS).sort());
  for (const [name, make] of Object.entries(PLAN_ON_SCENARIOS)) {
    const sc = make();
    const text = flatten(renderPlanSection(sc.config as never, sc.states as never));
    assert.equal(text.length, golden[name]?.length, name + " length");
    assert.equal(sha(text), golden[name]?.sha256, name);
    assert.equal(flatten(renderPlanSection(sc.config as never, sc.states as never, NOW_MS)), text, name + " with a given moment");
    assert.equal(flatten(renderPlanSection(sc.config as never, sc.states as never, NaN)), text, name + " with an unusable moment");
    const s2 = buildPlanSnapshotWithHelpers(sc.config as never, sc.states as never, NOW_MIN);
    assert.equal(s2.helpers, null, name);
    assert.deepEqual(s2.overrides, []);
    const { helpers: _h, ...rest } = s2;
    assert.equal(JSON.stringify(rest), JSON.stringify(buildPlanSnapshot(sc.config as never, sc.states as never)), name + " snapshot");
    assert.equal(presentPlan(s2).overrideBlock, null);
    assert.equal(presentPlan(s2).overridesLine, OVERRIDES_LINE_NONE);
  }
});

test("flag off: nothing is read, whatever the helper entities hold", () => {
  const trap = new Proxy({}, { get: () => { throw new Error("states read with the flag off"); }, has: () => { throw new Error("states read"); } });
  for (const c of [{ ...BASE_CONFIG }, { ...BASE_CONFIG, show_plan: false, plan: PLAN_CONFIG }, { ...BASE_CONFIG, show_plan: "true" }]) {
    assert.equal(flatten(renderPlanSection(c as never, trap as never, NOW_MS)), "");
  }
});

// ---- policy read from the helpers ----------------------------------------------------------------------------------------------------

test("a complete, confirmed policy is read into the plan core's configuration; nothing running", () => {
  const snap = snapOf(configured());
  const h = snap.helpers;
  assert.ok(h && h.policy.ok);
  if (!h || !h.policy.ok) return;
  assert.deepEqual({ ...h.policy.config }, { minExpiryMin: 15, holdDefaultMin: 240, holdCapMin: 1440, skipUntilMin: 420, skipCapMin: 1440, cutDefaultMin: 1440, cutCapMin: 4320, cutReservePct: 80 });
  assert.deepEqual(h.missing, []);
  assert.deepEqual(h.active, []);
  assert.deepEqual(h.problems, []);
  assert.deepEqual(snap.overrides, []);
  assert.deepEqual(h.revision, { known: true, value: 12, reason: "" });
  const vm = presentPlan(snap);
  assert.equal(vm.overridesLine, OVERRIDES_LINE_NONE_HELPER);
  const b = vm.overrideBlock;
  assert.ok(b);
  assert.equal(b.policyOk, true);
  assert.match(b.policyLine, /Hold battery default 4 h, up to 1 day/);
  assert.match(b.policyLine, /Skip tonight until 07:00, up to 1 day/);
  assert.match(b.policyLine, /Prepare for power cut default 1 day, up to 3 days, reserve 80 %/);
  assert.match(b.policyLine, /Hard ceilings.*3 days, 1 day 12 h, 7 days/);
  assert.equal(b.revisionText, "Plan revision 12 (stored in the plan helper).");
  assert.deepEqual(b.proposed, [], "no proposal is shown while the limits are in force");
  assert.deepEqual(b.rows, []);
});

test("every policy entity is needed: a missing one makes the limits unusable, names it, and never falls back to the proposed values", () => {
  for (const key of ["min_expiry", "hold_default", "hold_cap", "skip_until", "skip_cap", "cut_default", "cut_cap", "cut_reserve", "confirmed"] as const) {
    const s = configured({ [HELPER_IDS[key]]: undefined });
    const h = snapOf(s).helpers;
    assert.ok(h, key);
    assert.equal(h.policy.ok, false, key);
    assert.equal("config" in h.policy, false, key);
    assert.deepEqual(h.missing, [HELPER_IDS[key]], key);
    const b = presentPlan(snapOf(s)).overrideBlock;
    assert.ok(b && !b.policyOk);
    assert.ok(b.reasons.length > 0);
    assert.match(b.policyLine, /not usable/);
    assert.equal(b.proposed.length, PROPOSED_DEFAULTS.length, "the proposal is shown, to be reviewed");
    assert.ok(!flatten(renderPlanSection(cfg(), s as never, NOW_MS)).includes("Limits set by you"));
    assert.ok(flatten(renderPlanSection(cfg(), s as never, NOW_MS)).includes("Proposed values (not in use)"));
  }
});

test("unreadable, out-of-bounds, off-step and unconfirmed values make the limits unusable", () => {
  const bad = (patch: Record<string, unknown>, why: RegExp) => {
    const h = snapOf(configured(patch)).helpers;
    assert.ok(h);
    assert.equal(h.policy.ok, false, JSON.stringify(patch));
    assert.match((h.policy as { reasons: string[] }).reasons.join(" "), why, JSON.stringify(patch));
  };
  bad({ [HELPER_IDS.confirmed]: { state: "off" } }, /not confirmed/);
  bad({ [HELPER_IDS.confirmed]: { state: "unavailable" } }, /not confirmed/);
  bad({ [HELPER_IDS.hold_cap]: { state: "unavailable" } }, /Hold battery maximum is not set/);
  bad({ [HELPER_IDS.hold_cap]: { state: "4325" } }, /Hold battery maximum can be at most/);
  bad({ [HELPER_IDS.hold_cap]: { state: "99999" } }, /can be at most/);
  bad({ [HELPER_IDS.cut_cap]: { state: "10085" } }, /can be at most/);
  bad({ [HELPER_IDS.skip_cap]: { state: "2165" } }, /can be at most/);
  bad({ [HELPER_IDS.hold_default]: { state: "243" } }, /steps of 5/);
  bad({ [HELPER_IDS.hold_default]: { state: "1500" } }, /longer than its maximum/);
  bad({ [HELPER_IDS.min_expiry]: { state: "0" } }, /at least/);
  bad({ [HELPER_IDS.min_expiry]: { state: "-5" } }, /at least/);
  bad({ [HELPER_IDS.cut_reserve]: { state: "9" } }, /at least 10 %/);
  bad({ [HELPER_IDS.cut_reserve]: { state: "101" } }, /at most 100 %/);
  bad({ [HELPER_IDS.cut_reserve]: { state: "80.5" } }, /whole number/);
  bad({ [HELPER_IDS.skip_until]: { state: "01:30:00" } }, /at least 03:00/);
  bad({ [HELPER_IDS.skip_until]: { state: "07:00:30" } }, /whole number/);
  bad({ [HELPER_IDS.skip_until]: { state: "teatime" } }, /Skip tonight ends at is not set/);
  bad({ [HELPER_IDS.min_expiry]: { state: "five" } }, /not set or cannot be read/);
});

test("the power-cut reserve may never be below the backup reserve the card reads", () => {
  const states = configured();
  states[PLAN_CONFIG.reserve] = { state: "90" };
  const h = snapOf(states).helpers;
  assert.ok(h);
  assert.equal(h.policy.ok, false);
  assert.match((h.policy as { reasons: string[] }).reasons.join(" "), /below the current backup reserve \(90 %\)/);
  states[PLAN_CONFIG.reserve] = { state: "80" };
  assert.equal(snapOf(states).helpers?.policy.ok, true, "equal is allowed");
  const noReserve = buildPlanSnapshotWithHelpers(planConfig({}, { reserve: undefined }) as never, configured() as never, NOW_MIN).helpers;
  assert.ok(noReserve && noReserve.policy.ok);
  assert.equal((noReserve.policy as { warnings: string[] }).warnings.length, 1, "an unknown reserve is a warning, not a guess");
});

test("a half-built helper (only some entities) is configured, unusable, and lists what is missing", () => {
  const states = planStates();
  states[HELPER_IDS.revision] = { state: "3" };
  const h = snapOf(states).helpers;
  assert.ok(h);
  assert.equal(h.policy.ok, false);
  assert.equal(h.missing.length, Object.keys(HELPER_IDS).length - 1);
  assert.deepEqual(h.revision, { known: true, value: 3, reason: "" });
  const text = flatten(renderPlanSection(cfg(), states as never, NOW_MS));
  assert.match(text, /Plan helper entities not found/);
  assert.match(text, /input_boolean\.ecco_plan_overrides_enabled/);
});

test("the stored revision: zero means none yet; an unreadable or non-whole value is unknown", () => {
  assert.equal(vmOf(configured({ [HELPER_IDS.revision]: { state: "0" } })).overrideBlock?.revisionText, "Plan revision: none recorded yet.");
  assert.match(vmOf(configured({ [HELPER_IDS.revision]: { state: "unavailable" } })).overrideBlock?.revisionText ?? "", /unknown \(The stored plan revision cannot be read/);
  assert.match(vmOf(configured({ [HELPER_IDS.revision]: { state: "2.5" } })).overrideBlock?.revisionText ?? "", /not a whole number/);
  assert.match(vmOf(configured({ [HELPER_IDS.revision]: { state: "-1" } })).overrideBlock?.revisionText ?? "", /not a whole number/);
});

// ---- active overrides: expiry and countdown ---------------------------------------------------------------------------------------------

test("an active override is read with its expiry and countdown; the plan core gets the same record", () => {
  const states = running(configured(), "hold_battery", 40, 200);
  const snap = snapOf(states);
  assert.deepEqual(snap.overrides, [{ kind: "hold_battery", startedAtMin: NOW_MIN - 40, expiresAtMin: NOW_MIN + 200 }]);
  const vm = presentPlan(snap);
  assert.equal(vm.overridesLine, "Quick overrides active: Hold battery (status only).");
  const row = vm.overrideBlock?.rows[0];
  assert.ok(row);
  assert.equal(row.label, "Hold battery");
  assert.equal(row.untilText, "until 2026-11-16 23:20");
  assert.equal(row.countdownText, "ends in 3 h 20 min");
  assert.match(row.effectText, /^Intended: /);
  const text = flatten(renderPlanSection(cfg(), states as never, NOW_MS));
  for (const needle of ["Hold battery", "until 2026-11-16 23:20", "ends in 3 h 20 min", "Status only: nothing in this view starts, cancels or enforces an override"]) assert.ok(text.includes(needle), needle);
  assert.ok(!text.includes("[fn]"), "no handler anywhere in the section");
});

test("at most one override per kind, all three can run together, and Prepare for power cut carries its reserve", () => {
  const states = running(running(running(configured(), "hold_battery", 5, 600), "skip_tonight", 5, 120), "prepare_power_cut", 5, 2900, 85);
  const snap = snapOf(states);
  assert.deepEqual(snap.overrides.map((o) => o.kind), ["hold_battery", "skip_tonight", "prepare_power_cut"]);
  assert.equal(snap.overrides[2]?.reservePct, 85);
  assert.equal(snap.overrides[0]?.reservePct, undefined);
  const rows = presentPlan(snap).overrideBlock?.rows ?? [];
  assert.equal(rows.length, 3);
  assert.match(rows[2]?.effectText ?? "", /raised to 85 %/);
  assert.equal(rows[2]?.countdownText, "ends in 2 days 20 min");
});

test("expiry boundary: an override whose expiry is now is over; one minute left is still shown", () => {
  assert.deepEqual(snapOf(running(configured(), "hold_battery", 30, 0)).overrides, []);
  assert.deepEqual(snapOf(running(configured(), "hold_battery", 30, -1)).overrides, []);
  const one = snapOf(running(configured(), "hold_battery", 30, 1));
  assert.equal(one.overrides.length, 1);
  assert.equal(presentPlan(one).overrideBlock?.rows[0]?.countdownText, "ends in 1 min");
  assert.deepEqual(snapOf(running(configured(), "hold_battery", 30, 0)).helpers?.problems, [], "an expired record is history, not a problem");
});

test("the instant comes from the timestamp, not from the text, so a time zone or clock change cannot move an expiry", () => {
  const states = configured();
  states[HELPER_IDS.hold_battery_start] = stamp(NOW_MS - 10 * MIN, "2001-01-01 00:00:00");
  states[HELPER_IDS.hold_battery_expires] = stamp(NOW_MS + 120 * MIN, "2030-01-01 07:00:00");
  const row = vmOf(states).overrideBlock?.rows[0];
  assert.equal(row?.countdownText, "ends in 2 h");
  assert.equal(row?.untilText, "until 2030-01-01 07:00");
  // The text alone is never enough.
  states[HELPER_IDS.hold_battery_expires] = { state: "2030-01-01 07:00:00" };
  const h = snapOf(states).helpers;
  assert.deepEqual(h?.active, []);
  assert.match(h?.problems.join(" ") ?? "", /Hold battery expiry has no timestamp/);
});

test("malformed records are reported, never trusted and never shown as active", () => {
  const problems = (states: States, nowMin: number | null = NOW_MIN) => snapOf(states, nowMin).helpers?.problems.join(" | ") ?? "";
  const active = (states: States) => snapOf(states).overrides.length;
  const hold = (startedMinAgo: number, endsIn: number) => running(configured(), "hold_battery", startedMinAgo, endsIn);

  // start at or after the expiry
  assert.equal(active(hold(-10, 10)), 0);
  assert.match(problems(hold(-10, 10)), /starts at or after its expiry/);
  assert.equal(active(hold(0, 0)), 0, "expired and zero-length: history");
  assert.match(problems(hold(-50, 10)), /starts at or after its expiry/);
  // the hard ceiling is exact: 72 h is allowed, one minute more is not
  assert.equal(active(hold(4320 - 10, 10)), 1);
  assert.equal(active(hold(4320 - 9, 10)), 0);
  assert.match(problems(hold(4320 - 9, 10)), /Hold battery lasts longer than its hard ceiling/);
  assert.equal(active(running(configured(), "skip_tonight", 2160 - 10, 10)), 1);
  assert.equal(active(running(configured(), "skip_tonight", 2160 - 9, 10)), 0);
  assert.equal(active(running(configured(), "prepare_power_cut", 10080 - 10, 10, 80)), 1);
  assert.equal(active(running(configured(), "prepare_power_cut", 10080 - 9, 10, 80)), 0);
  assert.equal(active(hold(1, 10 * 525600)), 0, "ten years is not an override");
  // a power cut needs a readable reserve inside the reserve limits
  for (const [value, ok] of [["10", true], ["100", true], ["9", false], ["101", false], ["85.5", false], ["unavailable", false], ["lots", false]] as const) {
    const s = running(configured(), "prepare_power_cut", 5, 60, 80);
    s[HELPER_IDS.prepare_power_cut_reserve] = { state: value };
    assert.equal(active(s), ok ? 1 : 0, "reserve " + value);
    if (!ok) assert.match(problems(s), /Prepare for power cut has no readable reserve inside 10-100 %/);
  }
  // unreadable records
  const unreadableEnd = configured({ [HELPER_IDS.skip_tonight_expires]: { state: "unavailable" } });
  assert.match(problems(unreadableEnd), /Skip tonight expiry cannot be read/);
  const textEnd = configured({ [HELPER_IDS.skip_tonight_expires]: { state: "soon", attributes: { timestamp: (NOW_MS + 60 * MIN) / 1000 } } });
  assert.match(problems(textEnd), /Skip tonight expiry is not a date and time/);
  const noStamp = running(configured(), "skip_tonight", 5, 60);
  noStamp[HELPER_IDS.skip_tonight_start] = { state: "2026-11-16 19:55:00" };
  assert.equal(active(noStamp), 0);
  assert.match(problems(noStamp), /Skip tonight start has no timestamp.*not trusted/);
  const badStamp = running(configured(), "skip_tonight", 5, 60);
  badStamp[HELPER_IDS.skip_tonight_expires] = { state: "2026-11-16 21:00:00", attributes: { timestamp: "x" } };
  assert.match(problems(badStamp), /no timestamp/);
  // an unreadable START of a record that is not running is history, not a problem
  const idleStart = configured({ [HELPER_IDS.hold_battery_start]: { state: "unavailable" } });
  assert.equal(problems(idleStart), "");
  // without the current time nothing can be judged, and nothing is shown as active
  const running3 = running(configured(), "hold_battery", 5, 60);
  assert.equal(snapOf(running3, null).overrides.length, 0);
  assert.match(problems(running3, null), /current time is not known/);
});

test("the section shows the problems in plain words and still shows nothing as active for a malformed record", () => {
  const states = running(configured(), "hold_battery", -10, 10);
  const text = flatten(renderPlanSection(cfg(), states as never, NOW_MS));
  assert.match(text, /Hold battery starts at or after its expiry\. The record is not trusted\./);
  assert.ok(text.includes(OVERRIDES_LINE_NONE_HELPER));
});

// ---- the plan core consumes what was read -----------------------------------------------------------------------------------------------

test("what is read drives the plan core exactly as a started override would: scheduling only and raise-only", () => {
  const states = running(running(configured(), "hold_battery", 5, 600), "prepare_power_cut", 5, 600, 85);
  const snap = snapOf(states);
  const view = { startsAllowed: { charge: true, export: true }, discretionaryRateEdits: true, backupReservePct: 20, exportStopSoc: 25 };
  const out = applyOverrides(view, snap.overrides, NOW_MIN);
  assert.equal(out.view.startsAllowed.export, false);
  assert.equal(out.view.startsAllowed.charge, true, "charging is never stopped");
  assert.equal(out.view.backupReservePct, 85);
  assert.equal(out.view.exportStopSoc, 85);
  const high = applyOverrides({ ...view, backupReservePct: 95, exportStopSoc: 95 }, snap.overrides, NOW_MIN);
  assert.equal(high.view.backupReservePct, 95, "never lowered");
  assert.equal(high.view.exportStopSoc, 95);
});

// ---- read only ---------------------------------------------------------------------------------------------------------------------------

test("reading never changes the states or the config, and the card makes no service call with helpers present", () => {
  const states = running(configured(), "prepare_power_cut", 5, 600, 85);
  const before = JSON.stringify(states);
  const config = planConfig();
  const configBefore = JSON.stringify(config);
  readOverrideHelpers(states as never, NOW_MIN, 20);
  buildPlanSnapshotWithHelpers(config as never, states as never, NOW_MIN);
  assert.equal(JSON.stringify(states), before);
  assert.equal(JSON.stringify(config), configBefore);

  const cardStates = running(configured(), "hold_battery", 20, 90, undefined, FROZEN_NOW);
  const { hass, calls } = makeHass(cardStates);
  const card = new Card();
  card.setConfig({ ...BASE_CONFIG, show_plan: true, plan: PLAN_CONFIG });
  card.hass = hass;
  const text = withFrozenClock(() => flatten(card.render()));
  assert.equal(calls.length, 0, "no service call");
  assert.ok(text.includes("ends in 1 h 30 min"), "the card shows the countdown against its own clock");
  assert.ok(text.includes("Hold battery"));
});

test("without a given moment the entry point uses the real clock", () => {
  const realNow = Date.now();
  const states = running(configured(), "skip_tonight", 10, 90, undefined, realNow);
  const text = flatten(renderPlanSection(cfg(), states as never));
  assert.match(text, /Skip tonight/);
  assert.match(text, /ends in 1 h (29|30|31) min/);
});

test("hostile helper text never becomes markup or reaches the page", () => {
  const evil = "<img src=x onerror=alert(1)>";
  const states = configured({
    [HELPER_IDS.skip_until]: { state: evil },
    [HELPER_IDS.hold_cap]: { state: evil },
    [HELPER_IDS.skip_tonight_expires]: { state: evil, attributes: { timestamp: (NOW_MS + 60 * MIN) / 1000 } },
    [HELPER_IDS.revision]: { state: evil },
  });
  const text = flatten(renderPlanSection(cfg(), states as never, NOW_MS));
  assert.ok(!text.includes("onerror") && !text.includes("<img"), "hostile text is not echoed");
});

// ---- static proofs -----------------------------------------------------------------------------------------------------------------------

const BLOCK_COMMENT = /\/\*[\s\S]*?\*\//g;
const LINE_COMMENT = /^\s*\/\/.*$/gm;
// Comments are stripped and double-quoted string contents blanked, so user-facing prose can neither trip nor hide a check.
const stripped = (f: string): string => readFileSync(new URL("../src/plan/" + f, import.meta.url), "utf8").replace(BLOCK_COMMENT, "").replace(LINE_COMMENT, "");
const read = (f: string): string => stripped(f).replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
const importsOf = (src: string): string[] => [...new Set([...src.matchAll(/^import[^;]*?from\s+"([^"]+)";/gms)].map((m) => m[1] as string))].sort();

test("static: the reader and the presenter are pure and read only (no write, service call, clock, storage or markup injection)", () => {
  const banned = [/\bcallService\b/, /\bhass\b/, /\bDate\b/, /localStorage/, /sessionStorage/, /\bfetch\s*\(/, /\bdocument\s*[.[]/, /\bwindow\s*[.[]/, /\bglobalThis\b/, /innerHTML/, /unsafeHTML/, /\bMath\.random\b/, /@click/, /<button/, /\bsetInterval\b/, /\bsetTimeout\b/, /\bclass\s/, /\basync\b|\bawait\b|\bPromise\b/];
  for (const f of ["helpers.ts", "present.ts", "adapter.ts"]) {
    const src = read(f);
    for (const b of banned) assert.ok(!b.test(src), f + " must not contain " + b);
  }
  assert.deepEqual(importsOf(stripped("helpers.ts")), ["../../../ecco-plan-core/src/index.ts", "../config", "./adapter.ts"]);
  assert.deepEqual(importsOf(stripped("present.ts")), ["../../../ecco-plan-core/src/index.ts", "./adapter.ts", "./helpers.ts"]);
  assert.deepEqual(importsOf(stripped("adapter.ts")), ["../../../ecco-plan-core/src/index.ts", "../config"], "the stage-2 adapter was not changed to read helpers");
});

test("static: the clock is read in exactly one place, the entry point, and the views stay free of handlers", () => {
  const view = read("view.ts");
  assert.equal([...view.matchAll(/\bDate\.now\(\)/g)].length, 1);
  assert.equal([...view.matchAll(/\bDate\b/g)].length, 1);
  for (const bad of [/@click/, /@change/, /@input/, /<button/, /<input/, /callService/, /innerHTML/, /unsafeHTML/, /\bhass\b/, /\bsetInterval\b/, /\bsetTimeout\b/]) assert.ok(!bad.test(view), "view.ts must not contain " + bad);
});

test("static: the helper entities are generic ecco_plan_ names of the three helper kinds only; no site value", () => {
  const ids = Object.values(HELPER_IDS) as string[];
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) {
    assert.match(id, /^(input_boolean|input_number|input_datetime)\.ecco_plan_[a-z_]+$/, id);
    assert.ok(!/(dongle|inverter|modbus|deye|sunsynk|wifi|mqtt)/i.test(id), id);
  }
});
