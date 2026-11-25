import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { renderPlanSection } from "../src/plan/view.ts";
import { CHIPS, presentPlan, STATUS_LINE } from "../src/plan/present.ts";
import { buildPlanSnapshot } from "../src/plan/adapter.ts";
import { BASE_CONFIG, P, idleStates, makeHass } from "./support/fixtures.ts";
import type { States } from "./support/fixtures.ts";
import { flatten, loadCardClass } from "./support/loadCard.ts";
import { SCENARIOS, renderScenario, withFrozenClock } from "./support/scenarios.ts";
import { PLAN_CONFIG, TABLE, planConfig, planStates, slotEntity, withAdvice, withTable } from "./support/planFixtures.ts";

const golden = JSON.parse(readFileSync(new URL("./golden/flag-off-render.json", import.meta.url), "utf8")) as Record<string, string>;
const D = BASE_CONFIG.dump_to_grid;
const SD = D.schedule;
const SF = BASE_CONFIG.schedule;

let Card: Awaited<ReturnType<typeof loadCardClass>>;
before(async () => {
  Card = await loadCardClass();
});

const section = (states: States, extra: Record<string, unknown> = {}, plan: Record<string, unknown> = {}): string =>
  flatten(renderPlanSection(planConfig(extra, plan) as never, states as never));

/** Only the STATIC template strings of a result: everything dynamic must arrive through bindings, never as markup. */
function statics(v: unknown): string {
  if (Array.isArray(v)) return v.map(statics).join("");
  const o = v as { strings?: readonly string[]; values?: unknown[] } | null;
  if (o && o.strings && o.values) return o.strings.join("") + o.values.map(statics).join("");
  return "";
}

const BLOCK_COMMENT = /\/\*[\s\S]*?\*\//g;
const LINE_COMMENT = /^\s*\/\/.*$/gm;
const stripComments = (src: string): string => src.replace(BLOCK_COMMENT, "").replace(LINE_COMMENT, "");

// ---- flag-off identity -------------------------------------------------------------------------------------------------------------

test("flag off: the card renders exactly as it did before the plan views existed (golden captured from the pre-plan source)", () => {
  for (const name of Object.keys(SCENARIOS)) {
    assert.equal(renderScenario(Card, name), golden[name], name);
  }
});

test("flag off in every other form (false, absent, truthy non-true) with a plan block present: still identical", () => {
  for (const name of Object.keys(SCENARIOS)) {
    for (const flag of [{ show_plan: false }, {}, { show_plan: "true" }, { show_plan: 1 }, { show_plan: "yes" }, { show_plan: null }]) {
      assert.equal(renderScenario(Card, name, { ...flag, plan: PLAN_CONFIG }), golden[name], name + " " + JSON.stringify(flag));
    }
  }
});

test("flag off: the plan entry point returns nothing and never reads a state", () => {
  const trap = new Proxy({}, { get: () => { throw new Error("states read with the flag off"); }, has: () => { throw new Error("states read"); } });
  for (const cfg of [{ ...BASE_CONFIG }, { ...BASE_CONFIG, show_plan: false }, { ...BASE_CONFIG, show_plan: "true" }, { ...BASE_CONFIG, show_plan: 1, plan: PLAN_CONFIG }]) {
    assert.equal(flatten(renderPlanSection(cfg as never, trap as never)), "");
  }
});

test("flag on: the existing card output is unchanged and the plan section is the only addition", () => {
  for (const name of Object.keys(SCENARIOS)) {
    const states = idleStates();
    SCENARIOS[name]?.patch?.(states);
    withTable(states);
    withAdvice(states);
    const plan = flatten(renderPlanSection(planConfig(SCENARIOS[name]?.layout ? { layout: SCENARIOS[name]?.layout } : {}) as never, states as never));
    assert.ok(plan.includes("Tomorrow's Plan"));
    // Extra helper states are only read by the plan section, so the tiles' own text is unchanged: compare with the same states, flag off.
    const on = withFrozenClock(() => {
      const card = new Card();
      card.setConfig({ ...BASE_CONFIG, ...(SCENARIOS[name]?.layout ? { layout: SCENARIOS[name]?.layout } : {}), show_plan: true, plan: PLAN_CONFIG });
      card.hass = makeHass(states).hass;
      return flatten(card.render());
    });
    assert.ok(on.includes(plan), name + ": the plan section sits inside the card");
    assert.equal(on.replace(plan, ""), golden[name], name + ": everything else is identical");
  }
});

test("no service call: rendering every scenario with the flag on makes zero calls", () => {
  for (const name of Object.keys(SCENARIOS)) {
    const states = planStates();
    SCENARIOS[name]?.patch?.(states);
    const { hass, calls } = makeHass(states);
    const card = new Card();
    card.setConfig({ ...BASE_CONFIG, ...(SCENARIOS[name]?.layout ? { layout: SCENARIOS[name]?.layout } : {}), show_plan: true, plan: PLAN_CONFIG });
    card.hass = hass;
    card.render();
    assert.equal(calls.length, 0, name);
  }
});

test("the plan sources contain no handler, button, service call, innerHTML or storage", () => {
  for (const f of ["view.ts", "present.ts", "adapter.ts"]) {
    const src = stripComments(readFileSync(new URL("../src/plan/" + f, import.meta.url), "utf8"));
    for (const bad of [/@click/, /@change/, /@input/, /<button/, /<input/, /callService/, /innerHTML/, /unsafeHTML/, /localStorage/, /sessionStorage/, /\bfetch\(/, /\bsetInterval\b/, /\bsetTimeout\b/]) {
      assert.ok(!bad.test(src), f + " must not contain " + bad);
    }
  }
  const view = readFileSync(new URL("../src/plan/view.ts", import.meta.url), "utf8");
  assert.ok(!/\bhass\b/.test(stripComments(view)), "the view takes states, never hass");
});

test("the plan-core import is pure: no new runtime dependency (package.json unchanged, only lit)", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { dependencies: Record<string, string>; devDependencies: Record<string, string> };
  assert.deepEqual(Object.keys(pkg.dependencies), ["lit"]);
  assert.deepEqual(Object.keys(pkg.devDependencies).sort(), ["esbuild", "typescript"]);
  const core = readFileSync(new URL("../../ecco-plan-core/package.json", import.meta.url), "utf8");
  assert.ok(!/"dependencies"/.test(core));
});

// ---- views for each state -----------------------------------------------------------------------------------------------------------

function allStates(): States {
  // charge schedule armed (ARMED), dump session active (EXECUTING) with one matching and one differing latched read-back
  const s = planStates();
  s[SF.armed] = { state: "on" };
  s[SF.power] = { state: "5000" };
  s[D.active] = { state: "on" };
  s[SD.armed] = { state: "on" };
  s["sensor.test_latched_power"] = { state: "2000" };
  s["sensor.test_latched_stop"] = { state: "40" };
  return s;
}
const latched = { dump_to_grid: { ...D, active_export_power: "sensor.test_latched_power", active_stop_soc: "sensor.test_latched_stop" } };

test("all five chips appear, each with text and an icon (never colour alone), plus Unknown", () => {
  const snap = buildPlanSnapshot(planConfig(latched) as never, allStates() as never);
  const vm = presentPlan(snap);
  const kinds = new Set([...vm.figures.map((f) => f.chip.kind), ...vm.settings.map((r) => r.chip.kind)]);
  for (const k of ["PROPOSED", "ARMED", "EXECUTING", "APPLIED_VERIFIED", "MISMATCH", "UNKNOWN"]) assert.ok(kinds.has(k as never), "missing " + k);
  const text = section(allStates(), latched);
  for (const label of ["Proposed", "Armed", "Executing", "Applied and verified", "Mismatch", "Unknown"]) assert.ok(text.includes(">" + label + "<"), label);
  for (const c of Object.values(CHIPS)) {
    assert.ok(c.label.length > 3 && c.icon.startsWith("mdi:") && c.meaning.length > 20, c.kind);
    assert.ok(text.includes("icon=" + c.icon) || !kinds.has(c.kind), c.kind + " icon");
  }
  assert.ok(text.includes("title=" + CHIPS.MISMATCH.meaning));
});

test("Tomorrow's Plan strip: the figures, the confidence, every figure's chip and the Why? detail", () => {
  const text = section(planStates());
  for (const label of ["Expected import", "Expected export", "Expected solar", "Charge finishes", "Reserve", "Confidence"]) assert.ok(text.includes(label), label);
  assert.ok(text.includes("4.5 kWh") && text.includes("2.2 kWh") && text.includes("11.4 kWh"));
  assert.ok(text.includes(">High<"));
  assert.ok(text.includes("20 %"));
  assert.ok(text.includes("<summary>Why?</summary>"));
  assert.ok(text.includes("grid energy Intelligence plans for the overnight charge"));
  // every figure carries a chip
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, planStates() as never));
  assert.equal(vm.figures.length, 6);
  assert.ok(vm.figures.every((f) => f.chip.label.length > 0));
});

test("unknowns are shown as unknown with their reason, never as a number", () => {
  const states = planStates(false);
  delete states[PLAN_CONFIG.reserve];
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, states as never));
  for (const key of ["import", "export", "solar", "finish", "reserve", "confidence"]) {
    const f = vm.figures.find((x) => x.key === key);
    assert.equal(f?.known, false, key);
    assert.equal(f?.text, "Unknown");
    assert.ok((f?.reason ?? "").length > 10, key);
    assert.equal(f?.chip.kind, "UNKNOWN");
  }
  const text = section(states);
  assert.ok(text.includes("not available"));
  assert.ok(!/\d+\.\d kWh/.test(text), "no kWh number when there is no advice");
});

test("a withheld advice states why (paused)", () => {
  const text = section(planStates(true, { paused: true }));
  assert.ok(text.includes("Intelligence is paused by the owner"));
  assert.ok(!/4\.5 kWh/.test(text));
});

test("timeline, nothing armed: six slots, each verified against the inverter, headline says the table is unchanged", () => {
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, planStates() as never));
  assert.equal(vm.tou.slots.length, 6);
  assert.ok(vm.tou.slots.every((s) => s.chip.kind === "APPLIED_VERIFIED" && s.mismatch === null));
  assert.match(vm.tou.headline, /as the inverter reports them/);
  assert.equal(vm.tou.slots.reduce((n, s) => n + s.spanMin, 0), 1440);
  const text = section(planStates());
  assert.ok(text.includes("Slot 1") && text.includes("Slot 6"));
  assert.ok(text.includes("02:00 charge from grid, 5000 W, to 80 %"));
});

test("timeline, mismatch: intended versus inverter in plain words, and the slot is flagged", () => {
  const states = planStates();
  states[SF.armed] = { state: "on" };
  states[SF.start] = { state: "2026-11-15 02:00:00" };
  states[SF.duration] = { state: "180" };
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, states as never));
  assert.equal(vm.tou.mismatchCount, 1);
  const bad = vm.tou.slots.find((s) => s.mismatch);
  assert.ok(bad);
  assert.match(bad.mismatch ?? "", /Slot 2 differs from the inverter: power 4000 W intended, 5000 W on the inverter/);
  assert.match(bad.mismatch ?? "", /does not apply it/);
  assert.equal(bad.chip.kind, "MISMATCH");
  assert.ok(bad.originText.includes("charge plan"));
  const text = section(states);
  assert.ok(text.includes("power 4000 W intended, 5000 W on the inverter"));
  assert.ok(text.includes("Mismatch"));
});

test("timeline, six-slot-infeasible plan: the reason is shown and the native table is unchanged", () => {
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
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, states as never));
  assert.equal(vm.tou.statusText, "Does not fit six slots");
  assert.match(vm.tou.headline, /does not fit the inverter's six slots/);
  assert.ok(vm.tou.reasons.some((r) => /Six native slots are not enough: this plan needs 8 distinct slots/.test(r)));
  assert.ok(vm.tou.slots.every((s) => s.chip.kind === "APPLIED_VERIFIED"), "the table shown is the unchanged native one");
  const text = section(states);
  assert.ok(text.includes("Six native slots are not enough"));
  assert.ok(text.includes("Nothing is truncated"));
});

test("timeline, unreadable table: says so and shows no slots", () => {
  const states = planStates();
  states[slotEntity(4, "soc")] = { state: "unknown" };
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, states as never));
  assert.equal(vm.tou.readable, false);
  assert.equal(vm.tou.slots.length, 0);
  assert.match(vm.tou.headline, /slot 4 target SOC/);
  const text = section(states);
  assert.ok(text.includes("no comparison is possible"));
  assert.ok(!text.includes('data-slot="1"'));
});

test("timeline, session owns the inverter: not compiled, with the single-writer reason", () => {
  const states = planStates();
  states[`binary_sensor.${P}_free_power_snapshot_valid`] = { state: "on" };
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, states as never));
  assert.equal(vm.tou.statusText, "Not compiled");
  assert.ok(vm.tou.reasons.some((r) => /Single writer: Free Power/.test(r)));
});

test("planned settings rows: values, time formatting, remarks for read-back and for an Intelligence proposal", () => {
  const states = allStates();
  states[SD.start] = { state: "2026-11-15 17:05:00" };
  const vm = presentPlan(buildPlanSnapshot(planConfig(latched) as never, planStates(true, { target: 90 }) && (withAdvice(states, { target: 90 }) as never)));
  const by = (p: string) => vm.settings.find((r) => r.path === p);
  assert.equal(by("export.startMin")?.text, "17:05");
  assert.equal(by("export.stopSoc")?.text, "25 %");
  assert.ok(by("export.stopSoc")?.remarks.some((r) => /system reports 40 %, not 25 %/.test(r)));
  assert.ok(by("charge.targetSoc")?.remarks.some((r) => /Intelligence suggests 90 % \(not adopted/.test(r)));
  assert.equal(by("charge.bufferMin")?.text, "Unknown");
});

test("status line and overrides line: advice-only wording, overrides are status only", () => {
  const vm = presentPlan(buildPlanSnapshot(planConfig() as never, planStates() as never));
  assert.equal(vm.statusLine, STATUS_LINE);
  assert.match(STATUS_LINE, /SHADOW \/ advice only/);
  assert.match(STATUS_LINE, /Nothing shown here is applied by this view/);
  assert.match(vm.overridesLine, /none active/);
  assert.match(vm.overridesLine, /needs a plan helper that does not exist yet/);
  const text = section(planStates());
  assert.ok(text.includes("role=\"status\""));
  assert.ok(text.includes("Read only"));
});

test("data never becomes markup: hostile entity text stays in bindings, not in the template", () => {
  const states = planStates();
  const evil = '<img src=x onerror="alert(1)">';
  states["sensor.ecco_intel_charge_target"] = {
    state: "80",
    attributes: { confidence: "HIGH", blockers: [{ code: "X", text: evil }], advice: { binding_constraint: evil, grid_charge_kwh: 3 } },
  };
  states[slotEntity(1, "charge")] = { state: evil };
  const result = renderPlanSection(planConfig() as never, states as never);
  assert.ok(!statics(result).includes("onerror"), "no hostile text in the static template");
  assert.ok(!statics(result).includes("<img"));
  // the hostile slot makes the table unreadable; the advice blocker text is displayed as data
  assert.ok(flatten(result).includes("Blocked: " + evil));
});

test("accessibility structure: labelled region, status role, definition list, details/summary, ordered slot list, no click targets", () => {
  const text = section(planStates());
  assert.ok(text.includes('aria-label="Plan, read only"'));
  assert.ok(text.includes("<dl "));
  assert.ok(text.includes("<details "));
  assert.ok(text.includes("<ol "));
  assert.ok(text.includes('aria-hidden="true"'));
  assert.ok(!text.includes("[fn]"), "no event handlers anywhere in the section");
});
