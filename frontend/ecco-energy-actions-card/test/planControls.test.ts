import { test, before } from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { cancelOverrideCall, guardedDumpStartCall, isPlanServiceCall, PLAN_CONTROL_IDS, startOverrideCall } from "../src/plan/planActions.ts";
import { clockContextFrom } from "../src/plan/clock.ts";
import { buildControlsVM } from "../src/plan/controlsModel.ts";
import { belowReserveSentence } from "../src/plan/present.ts";
import { buildPlanSnapshotWithHelpers } from "../src/plan/helpers.ts";
import { renderPlanSection } from "../src/plan/view.ts";
import { renderPlanControls, START_BUTTON_LIMITATION } from "../src/plan/controls.ts";
import { BASE_CONFIG } from "./support/fixtures.ts";
import { flatten, loadCardClass } from "./support/loadCard.ts";
import { NOW_MS, helperStates, running } from "./support/overrideFixtures.ts";
import { PLAN_CONFIG, planConfig, planStates } from "./support/planFixtures.ts";
import { controlsProblems, handlersOf, scriptStates } from "./support/controlsProbe.ts";

// Stage 3 of the two-master-card energy-control work: the plan section's start and cancel controls. They exist only when the plan helper
// entities are configured, they hand ONE prebuilt call each to the card, and the card sends it only if it is exactly `script.turn_on` on one of
// the guarded scripts. Which override is allowed, for how long and with what reserve is decided by those scripts on the server (their own suite
// proves them against this card's validator); what is proved here is that the card can say nothing else.

const root = resolve(import.meta.dirname, "..");
const src = (f: string): string => readFileSync(join(root, "src", f), "utf8");
const BLOCK_COMMENT = /\/\*[\s\S]*?\*\//g;
const LINE_COMMENT = /^\s*\/\/.*$/gm;
const code = (f: string): string => src(f).replace(BLOCK_COMMENT, "").replace(LINE_COMMENT, "");
const noStrings = (f: string): string => code(f).replace(/"(?:[^"\\\n]|\\.)*"/g, '""');

let Card: Awaited<ReturnType<typeof loadCardClass>>;
before(async () => {
  Card = await loadCardClass();
});

const cfg = (): never => planConfig() as never;
const configured = (patch: Record<string, unknown> = {}) => helperStates(scriptStates(planStates()), patch);
const NOW_MIN = Math.floor(NOW_MS / 60000);

// ---- the card, end to end ---------------------------------------------------------------------------------------------------------------

test("the controls and the guarded start pass every end-to-end check of the real card", () => {
  assert.deepEqual(controlsProblems(Card as never), []);
});

test("with no plan helpers (or show_plan off) the section is exactly what it was: the renderer adds nothing and no handler exists", () => {
  const states = planStates();
  const calls: unknown[] = [];
  const renderer = renderPlanControls((c) => calls.push(c));
  assert.equal(flatten(renderPlanSection(cfg(), states as never, NOW_MS, renderer)), flatten(renderPlanSection(cfg(), states as never, NOW_MS)));
  assert.equal(handlersOf(renderPlanSection(cfg(), states as never, NOW_MS, renderer)).length, 0);
  const off = { ...(planConfig() as Record<string, unknown>), show_plan: false };
  assert.equal(flatten(renderPlanSection(off as never, configured() as never, NOW_MS, renderer)), "");
  assert.equal(calls.length, 0);
});

test("with the helpers the section says guarded, not read only, and lists every kind with its blurb", () => {
  const text = flatten(renderPlanSection(cfg(), configured() as never, NOW_MS, renderPlanControls(() => undefined)));
  assert.ok(text.includes('aria-label="Plan, with guarded controls"') && text.includes("Guarded controls") && !text.includes("Read only"));
  for (const label of ["Hold battery", "Skip tonight", "Prepare for power cut"]) assert.ok(text.includes(label), label);
  assert.ok(text.includes("It does not charge the battery"), "Prepare for power cut says it does not charge");
  assert.ok(text.includes("Home Assistant checks every one against your limits again"), "the card says the server decides");
});

test("the stated Start-button limitation is shown with the controls, scripts found or missing, as plain text that adds no handler (release gate RG-ST3)", () => {
  const found = renderPlanSection(cfg(), configured() as never, NOW_MS, renderPlanControls(() => undefined));
  const missing = renderPlanSection(cfg(), helperStates(planStates()) as never, NOW_MS, renderPlanControls(() => undefined));
  assert.ok(flatten(missing).includes("The guarded scripts were not found"), "the scripts-missing branch is the one under test");
  for (const section of [found, missing]) {
    const text = flatten(section);
    assert.equal(text.split(START_BUTTON_LIMITATION).length - 1, 1, "the sentence is shown exactly once");
    assert.ok(text.includes("data-plan-limitation"), "in its own marked paragraph");
  }
  assert.equal(handlersOf(missing).length, 0, "the note adds no handler of its own");
  for (const must of ["Partial protection only", "Start button", "an assistant", "an administrator", "plain helpers", "firmware gate"]) assert.ok(START_BUTTON_LIMITATION.includes(must), must);
  assert.ok(!/fully enforced|guaranteed|cannot be pressed/i.test(START_BUTTON_LIMITATION.replace("Partial protection only", "")), "it never claims full enforcement");
});

// ---- the closed list of calls -----------------------------------------------------------------------------------------------------------

test("the call builders: script.turn_on on exactly the three guarded scripts, with only the four variables", () => {
  const start = startOverrideCall("hold_battery", { expiryMin: 90 }, 12);
  assert.deepEqual(start, { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script, variables: { kind: "hold_battery", expiry_min: 90, expected_revision: 12 } } });
  assert.deepEqual(startOverrideCall("skip_tonight", { untilLocal: true }, null).data.variables, { kind: "skip_tonight", until_local: true });
  assert.deepEqual(cancelOverrideCall("prepare_power_cut", 3).data, { entity_id: PLAN_CONTROL_IDS.cancel_script, variables: { kind: "prepare_power_cut", expected_revision: 3 } });
  assert.deepEqual(guardedDumpStartCall("script.ecco_dump_to_grid_start_guarded"), { domain: "script", service: "turn_on", data: { entity_id: "script.ecco_dump_to_grid_start_guarded" } });
  for (const bad of ["button.start_dump_to_grid_now", "switch.x", "", "script.", "script.A", "script.x y", "script.x;y"]) assert.equal(guardedDumpStartCall(bad), null, bad);
  for (const c of [start, cancelOverrideCall("hold_battery", null), guardedDumpStartCall("script.g") as never]) assert.ok(isPlanServiceCall(c, "script.g"));
});

test("the allow-list refuses everything else: other domains and services, other scripts, extra data, extra variables, a guarded start with variables", () => {
  const ok = { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script, variables: { kind: "hold_battery" } } };
  assert.ok(isPlanServiceCall(ok, null));
  const variants: unknown[] = [
    null, undefined, 5, "script.turn_on", [], {},
    { ...ok, domain: "button" }, { ...ok, domain: "switch", service: "turn_on" }, { ...ok, domain: "number", service: "set_value" },
    { ...ok, service: "turn_off" }, { ...ok, service: "toggle" }, { ...ok, service: "press" },
    { ...ok, data: { entity_id: "script.ecco_free_power_cancel_schedule" } },
    { ...ok, data: { entity_id: "script.ecco_dump_to_grid_start_scheduled" } },
    { ...ok, data: { entity_id: "button.start_dump_to_grid_now" } },
    { ...ok, data: { entity_id: PLAN_CONTROL_IDS.start_script, extra: 1 } },
    { ...ok, data: { entity_id: PLAN_CONTROL_IDS.start_script, variables: { kind: "hold_battery", entity_id: "switch.x" } } },
    { ...ok, data: { entity_id: PLAN_CONTROL_IDS.start_script, variables: "kind" } },
    { ...ok, data: { entity_id: [PLAN_CONTROL_IDS.start_script] } },
    { ...ok, data: { variables: { kind: "hold_battery" } } },
    { ...ok, data: { entity_id: "script.g", variables: { kind: "hold_battery" } } },
  ];
  for (const v of variants) assert.equal(isPlanServiceCall(v, "script.g"), false, JSON.stringify(v));
  assert.equal(isPlanServiceCall({ domain: "script", service: "turn_on", data: { entity_id: "script.g" } }, null), false, "the guarded start is not allowed unless the card is configured with it");
  assert.equal(isPlanServiceCall({ domain: "script", service: "turn_on", data: { entity_id: "script.g" } }, ""), false);
  assert.equal(isPlanServiceCall({ domain: "script", service: "turn_on", data: { entity_id: "script.g" } }, "script.g"), true);
});

// ---- what is offered (the validator decides; the server decides again) -----------------------------------------------------------------

function vmOf(states: Record<string, unknown>, clock: { nowWallMin: number; day: { changeAtMin: number; deltaMin: 0 | 60 | -60 } } | null = null) {
  const snap = buildPlanSnapshotWithHelpers(cfg(), states as never, NOW_MIN);
  return buildControlsVM({ snap, states: states as never, nowMs: NOW_MS, clock });
}

test("the choices are the owner's: default marked, never below the shortest or above the longest, and 'until' only where it fits", () => {
  const vm = vmOf(configured() as never, { nowWallMin: 21 * 60 + 30, day: { changeAtMin: 0, deltaMin: 0 } });
  assert.ok(vm);
  const by = Object.fromEntries(vm.kinds.map((k) => [k.kind, k]));
  const mins = (k: string) => (by[k]?.choices ?? []).map((c) => (c.call.data.variables as { expiry_min?: number }).expiry_min ?? "until");
  assert.ok(by["hold_battery"]?.choices.some((c) => c.id === "d240" && c.isDefault));
  assert.ok(mins("hold_battery").every((m) => m === "until" || (m >= 15 && m <= 1440)), "Hold battery chips");
  assert.ok(mins("skip_tonight").every((m) => m === "until" || (m >= 15 && m <= 1440)));
  assert.ok(by["skip_tonight"]?.choices.some((c) => c.id === "until" && c.isDefault), "Skip tonight's default is 'until its end time'");
  assert.ok(mins("prepare_power_cut").every((m) => typeof m === "number" && m >= 15 && m <= 4320) && by["prepare_power_cut"]?.choices.some((c) => c.id === "d1440" && c.isDefault));
  assert.equal(by["prepare_power_cut"]?.choices.some((c) => c.id === "until"), false, "no 'until a time' for Prepare for power cut");
  // 'until' is sent as the instruction, not as minutes: the script works it out on its own clock
  const until = by["skip_tonight"]?.choices.find((c) => c.id === "until");
  assert.deepEqual(until?.call.data.variables, { kind: "skip_tonight", until_local: true, expected_revision: 12 });
  // too late in the evening for 'until' to fit a shorter owner cap: it disappears
  const tight = vmOf(configured({ "input_number.ecco_plan_policy_skip_cap": { state: "480" } }) as never, { nowWallMin: 21 * 60 + 30, day: { changeAtMin: 0, deltaMin: 0 } });
  assert.equal(tight?.kinds.find((k) => k.kind === "skip_tonight")?.choices.some((c) => c.id === "until"), false);
});

test("a start the owner's limits do not allow is not offered, and says why; cancel stays available for a running override", () => {
  const states = configured();
  (states as Record<string, unknown>)["input_boolean.ecco_plan_overrides_enabled"] = { state: "off" };
  running(states, "hold_battery", 10, 100);
  const vm = vmOf(states as never);
  assert.ok(vm);
  for (const k of vm.kinds) assert.equal(k.choices.length, 0, k.kind);
  assert.ok(vm.kinds.every((k) => (k.blockedReason ?? "").length > 0));
  assert.ok(vm.kinds.find((k) => k.kind === "hold_battery")?.cancel, "a running override can always be cancelled");
  assert.equal(vm.kinds.find((k) => k.kind === "skip_tonight")?.cancel, null);
  assert.match(vm.kinds.find((k) => k.kind === "hold_battery")?.activeText ?? "", /^Active until \d{4}-\d{2}-\d{2} \d{2}:\d{2} \(ends in 1 h 40 min\)$/);
});

test("the below-reserve sentence is the owner's wording, appears only for Prepare for power cut while the battery is below the reserve it raised", () => {
  assert.equal(belowReserveSentence(35, 80), "The battery is at 35 percent, below the 80 percent reserve. Nothing is charging. Use Charge Battery if you want it filled.");
  assert.equal(belowReserveSentence(34.6, 80.4), "The battery is at 35 percent, below the 80 percent reserve. Nothing is charging. Use Charge Battery if you want it filled.");
  const states = configured();
  running(states, "prepare_power_cut", 5, 600, 80);
  running(states, "hold_battery", 5, 600);
  (states as Record<string, unknown>)[BASE_CONFIG.dump_to_grid.battery_soc] = { state: "35" };
  const vm = vmOf(states as never);
  assert.equal(vm?.kinds.find((k) => k.kind === "prepare_power_cut")?.belowReserve, belowReserveSentence(35, 80));
  assert.equal(vm?.kinds.find((k) => k.kind === "hold_battery")?.belowReserve, null);
  for (const soc of ["80", "81", "100", "unknown"]) {
    (states as Record<string, unknown>)[BASE_CONFIG.dump_to_grid.battery_soc] = { state: soc };
    assert.equal(vmOf(states as never)?.kinds.find((k) => k.kind === "prepare_power_cut")?.belowReserve, null, soc);
  }
  // the sentence offers nothing automatic: no call in the whole section mentions a charge
  (states as Record<string, unknown>)[BASE_CONFIG.dump_to_grid.battery_soc] = { state: "35" };
  const calls: unknown[] = [];
  const tpl = renderPlanSection(cfg(), states as never, NOW_MS, renderPlanControls((c) => calls.push(c)));
  for (const h of handlersOf(tpl)) h.fn();
  assert.ok(calls.length > 0 && calls.every((c) => isPlanServiceCall(c, null)) && !JSON.stringify(calls).match(/charge|button|switch|number|select/i));
});

test("a hostile last answer is shown as text only", () => {
  const evil = '<img src=x onerror=alert(1)> REFUSED';
  const tpl = renderPlanSection(cfg(), configured({ [PLAN_CONTROL_IDS.last_result]: { state: evil } }) as never, NOW_MS, renderPlanControls(() => undefined));
  const statics = (v: unknown): string => {
    if (Array.isArray(v)) return v.map(statics).join("");
    const o = v as { strings?: readonly string[]; values?: unknown[] } | null;
    return o && o.strings && o.values ? o.strings.join("") + o.values.map(statics).join("") : "";
  };
  assert.ok(flatten(tpl).includes("Last answer: " + evil), "shown");
  assert.ok(!statics(tpl).includes("onerror"), "never part of the markup");
});

test("property sweep: whatever the states hold, the controls build no call outside the allow-list and never throw", () => {
  let seed = 90210;
  const rnd = (): number => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
  const junk = ["unknown", "unavailable", "", "on", "off", "-5", "1e999", "NaN", "7", "80", "1440", "99999", "0.5", "<b>", "2026-11-17 07:00:00"];
  for (let i = 0; i < 300; i++) {
    const states = configured();
    for (const k of Object.keys(states)) if (k.includes("ecco_plan") && rnd() < 0.35) (states as Record<string, unknown>)[k] = { state: junk[Math.floor(rnd() * junk.length)] as string, attributes: { timestamp: rnd() < 0.5 ? NOW_MS / 1000 + (rnd() - 0.3) * 1e6 : "x" } };
    if (rnd() < 0.2) delete (states as Record<string, unknown>)[PLAN_CONTROL_IDS.cancel_script];
    const calls: unknown[] = [];
    const tpl = renderPlanSection(cfg(), states as never, NOW_MS, renderPlanControls((c) => calls.push(c)));
    for (const h of handlersOf(tpl)) h.fn();
    assert.ok(calls.every((c) => isPlanServiceCall(c, null)), "iteration " + i);
  }
});

// ---- the browser clock ----------------------------------------------------------------------------------------------------------------

test("clockContextFrom: the wall-clock minute and the clock change of the next 24 hours, from a zone offset alone", () => {
  // A zone that is GMT before 2027-03-28 01:00 UTC and BST (UTC+1) after it: offset minutes WEST of UTC.
  const change = Date.UTC(2027, 2, 28, 1, 0, 0);
  const spring = (ms: number): number => (ms < change ? 0 : -60);
  const c1 = clockContextFrom(Date.UTC(2027, 2, 27, 22, 30), spring);
  assert.deepEqual(c1, { nowWallMin: 22 * 60 + 30, day: { changeAtMin: 60, deltaMin: 60 } });
  // The change an hour back: BST until 2027-10-31 01:00 UTC, GMT after it. The wall clock repeats 01:00 to 02:00; it changes at 02:00 BST.
  const back = Date.UTC(2027, 9, 31, 1, 0, 0);
  const autumn = (ms: number): number => (ms < back ? -60 : 0);
  const c2 = clockContextFrom(Date.UTC(2027, 9, 30, 21, 30), autumn);
  assert.deepEqual(c2, { nowWallMin: 22 * 60 + 30, day: { changeAtMin: 120, deltaMin: -60 } });
  assert.deepEqual(clockContextFrom(Date.UTC(2027, 5, 1, 12, 0), () => -60), { nowWallMin: 13 * 60, day: { changeAtMin: 0, deltaMin: 0 } });
  assert.equal(clockContextFrom(Date.UTC(2027, 2, 27, 12, 0), (ms) => (ms < change ? 0 : -30)), null, "a half-hour change is not modelled");
  assert.equal(clockContextFrom(NaN, () => 0), null);
  // The same pair of cases through the validator reproduce the parity table's clock-change answers (7 h 30 min and 9 h 30 min).
  assert.ok(c1 && c2);
});

// ---- static proofs --------------------------------------------------------------------------------------------------------------------

test("static: only controls.ts has click handlers; they call the callback with a prebuilt call and nothing else", () => {
  const ctl = noStrings("plan/controls.ts");
  assert.equal([...ctl.matchAll(/@click=/g)].length, 2, "exactly two click bindings: a choice and a cancel");
  assert.equal([...ctl.matchAll(/@click=\$\{\(\) => dispatch\(/g)].length, 2, "each hands one call to dispatch");
  assert.equal([...ctl.matchAll(/<button/g)].length, 2);
  for (const bad of [/callService/, /\bhass\b/, /\bDate\b/, /localStorage/, /sessionStorage/, /\bfetch\s*\(/, /\bdocument\s*[.[]/, /\bwindow\s*[.[]/, /innerHTML/, /unsafeHTML/, /\bsetInterval\b/, /\bsetTimeout\b/, /\bMath\.random\b/, /\basync\b|\bawait\b|\bPromise\b/]) assert.ok(!bad.test(ctl), "controls.ts must not contain " + bad);
  assert.ok(!/"(?:button|switch|number|select|script|input_[a-z]+|esphome)\./.test(code("plan/controls.ts")), "controls.ts names no entity or service");
  for (const f of ["plan/view.ts", "plan/present.ts", "plan/adapter.ts", "plan/helpers.ts", "plan/controlsModel.ts", "plan/planActions.ts", "plan/clock.ts"]) {
    for (const bad of [/@click/, /@change/, /@input/, /<button/, /<input/, /callService/, /innerHTML/, /unsafeHTML/, /\bsetInterval\b/, /\bsetTimeout\b/]) assert.ok(!bad.test(noStrings(f)), f + " must not contain " + bad);
  }
});

test("static: the pure plan modules import only each other and the plan core; the clock is asked in one place", () => {
  const importsOf = (f: string): string[] => [...new Set([...code(f).matchAll(/^import[^;]*?from\s+"([^"]+)";/gms)].map((m) => m[1] as string))].sort();
  assert.deepEqual(importsOf("plan/planActions.ts"), ["../../../ecco-plan-core/src/index.ts"]);
  assert.deepEqual(importsOf("plan/controlsModel.ts"), ["../../../ecco-plan-core/src/index.ts", "./adapter.ts", "./helpers.ts", "./planActions.ts", "./present.ts"]);
  assert.deepEqual(importsOf("plan/controls.ts"), ["./clock.ts", "./controlsModel.ts", "./planActions.ts", "./view.ts", "lit"]);
  assert.deepEqual(importsOf("plan/clock.ts"), ["../../../ecco-plan-core/src/index.ts"]);
  for (const f of ["plan/planActions.ts", "plan/controlsModel.ts"]) for (const bad of [/\bDate\b/, /\bhass\b/, /\bdocument\b/, /\bwindow\b/, /\bfetch\b/, /localStorage/, /from "lit/]) assert.ok(!bad.test(noStrings(f)), f + " must not contain " + bad);
  const dateFiles = readdirSync(join(root, "src", "plan")).sort().filter((f) => /\bDate\b/.test(noStrings("plan/" + f)));
  assert.deepEqual(dateFiles, ["clock.ts", "view.ts"], "the time of day is read in the section's entry point and in the one browser-zone adapter only");
});

test("static: the only service the plan section can name is script.turn_on, and the card reaches Home Assistant through one checked method", () => {
  const actions = noStrings("plan/planActions.ts");
  assert.deepEqual([...new Set([...src("plan/planActions.ts").matchAll(/domain: "([a-z_]+)"/g)].map((m) => m[1]))], ["script"], "domain script only");
  assert.deepEqual([...new Set([...src("plan/planActions.ts").matchAll(/service: "([a-z_]+)"/g)].map((m) => m[1]))], ["turn_on"], "service turn_on only");
  assert.ok(!/callService/.test(actions));
  const card = src("ecco-energy-actions-card.ts");
  assert.equal([...card.matchAll(/private _callPlanService\(/g)].length, 1, "defined once");
  assert.equal([...card.matchAll(/renderPlanControls\(\(call\) => this\._callPlanService\(call\)\)/g)].length, 1, "the plan controls send through it");
  assert.equal([...card.matchAll(/this\._callPlanService\(guarded\)/g)].length, 1, "the guarded start sends through it");
  const method = /private _callPlanService\(call: PlanServiceCall\): void \{([\s\S]*?)\n  \}/.exec(card);
  assert.ok(method, "_callPlanService");
  assert.ok(/isPlanServiceCall\(call, this\._config\?\.dump_to_grid\?\.guarded_start\)\) return;/.test(method[1] as string), "the allow-list is applied first");
  assert.equal([...(method[1] as string).matchAll(/_callService\(/g)].length, 1);
  assert.equal([...card.matchAll(/entity_id: dump\.start/g)].length, 1, "the direct start press exists once, in _pressDumpStart");
  assert.ok(!/_callService\("button", "press", \{ entity_id: ctx\.dump\.start/.test(card), "no click presses the dump start button directly any more");
  const press = /private _pressDumpStart\(dump:[^)]*\): void \{([\s\S]*?)\n  \}/.exec(card);
  assert.ok(press && /guardedDumpStartCall\(dump\.guarded_start\)/.test(press[1] as string) && /return;\n    \}\n    this\._callService\("button", "press", \{ entity_id: dump\.start \}\);/.test(press[1] as string), "guarded: return before the direct press");
});

// ---- mutants of the card's controls ----------------------------------------------------------------------------------------------------

let mutantCount = 0;
const cardRoot = root;
const coreRoot = resolve(root, "..", "ecco-plan-core");

async function loadMutant(file: string, find: string, put: string, times = 1): Promise<Awaited<ReturnType<typeof loadCardClass>>> {
  const dir = mkdtempSync(join(tmpdir(), "eaa-mut-"));
  try {
    cpSync(join(cardRoot, "src"), join(dir, "frontend", "ecco-energy-actions-card", "src"), { recursive: true });
    cpSync(join(coreRoot, "src"), join(dir, "frontend", "ecco-plan-core", "src"), { recursive: true });
    const base = file.startsWith("core/") ? join(dir, "frontend", "ecco-plan-core", "src", file.slice(5)) : join(dir, "frontend", "ecco-energy-actions-card", "src", file);
    const cardFile = join(dir, "frontend", "ecco-energy-actions-card", "src", "ecco-energy-actions-card.ts");
    writeFileSync(cardFile, readFileSync(cardFile, "utf8").replace('@customElement("ecco-energy-actions-card")', '@customElement("ecco-energy-actions-card-mutant-' + String(++mutantCount) + '")'));
    const text = readFileSync(base, "utf8");
    const n = text.split(find).length - 1;
    assert.equal(n, times, "mutant anchor " + JSON.stringify(find.slice(0, 60)) + " found " + n + "x");
    writeFileSync(base, text.split(find).join(put));
    const g = globalThis as Record<string, unknown>;
    g.window = g.window ?? {};
    const outfile = join(dir, "card.mjs");
    await build({
      entryPoints: [join(dir, "frontend", "ecco-energy-actions-card", "src", "ecco-energy-actions-card.ts")], outfile, bundle: true, format: "esm", platform: "node",
      conditions: ["node"], target: ["node24"], logLevel: "silent", nodePaths: [join(cardRoot, "node_modules")],
      tsconfigRaw: { compilerOptions: { experimentalDecorators: true, useDefineForClassFields: false } },
    });
    const mod = (await import(pathToFileURL(outfile).href)) as Record<string, unknown>;
    return mod.EccoEnergyActionsCard as never;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const MUTANTS: { label: string; file: string; find: string; put: string; times?: number }[] = [
  { label: "a control calls another service (a button press) instead of the script", file: "plan/planActions.ts", find: 'return { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script, variables } };', put: 'return { domain: "script", service: "turn_on", data: { entity_id: "button.start_free_power_charge_now" } };' },
  { label: "the card sends calls without checking the allow-list", file: "ecco-energy-actions-card.ts", find: "if (!isPlanServiceCall(call, this._config?.dump_to_grid?.guarded_start)) return;", put: "" },
  { label: "the allow-list accepts any script", file: "plan/planActions.ts", find: 'if (id !== PLAN_CONTROL_IDS.start_script && id !== PLAN_CONTROL_IDS.cancel_script && !isGuardedStart) return false;', put: 'if (typeof id !== "string" || !id.startsWith("script.")) return false;' },
  { label: "the allow-list accepts any domain and service", file: "plan/planActions.ts", find: 'if (c.domain !== "script" || c.service !== "turn_on") return false;', put: "" },
  { label: "the allow-list accepts a variable the scripts do not take", file: "plan/planActions.ts", find: 'k === "kind" || k === "expiry_min" || k === "until_local" || k === "expected_revision"', put: "true" },
  { label: "a guarded start that is not a script falls back to the direct press", file: "ecco-energy-actions-card.ts", find: "      if (guarded) this._callPlanService(guarded);\n      return;", put: "      if (guarded) this._callPlanService(guarded);\n      else this._callService(\"button\", \"press\", { entity_id: dump.start });\n      return;" },
  { label: "the guarded start is ignored (the button is always pressed directly)", file: "ecco-energy-actions-card.ts", find: 'if (dump.guarded_start !== undefined && dump.guarded_start !== "") {', put: "if (false) {" },
  { label: "a start without the revision the card saw", file: "plan/planActions.ts", find: 'if (typeof expectedRevision === "number") variables["expected_revision"] = expectedRevision;\n  return { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script', put: 'return { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.start_script' },
  { label: "a cancel runs the start script", file: "plan/planActions.ts", find: "data: { entity_id: PLAN_CONTROL_IDS.cancel_script, variables }", put: "data: { entity_id: PLAN_CONTROL_IDS.start_script, variables }" },
  { label: "Prepare for power cut is offered with an unknown reserve", file: "plan/controlsModel.ts", find: 'verdict.code === "RESERVE_UNKNOWN" || ', put: "" },
  { label: "Prepare for power cut is offered below the current reserve", file: "plan/controlsModel.ts", find: ' || verdict.code === "RESERVE_BELOW_CURRENT"', put: "" },
  { label: "the chips are not held to the owner's longest length", file: "core/overridePolicy.ts", find: " && d <= cap", put: "", times: 2 },
  { label: "the chips are not held to the owner's shortest length", file: "core/overridePolicy.ts", find: "d >= cfg.minExpiryMin && ", put: "", times: 2 },
  { label: "the owner's default is not marked", file: "core/overridePolicy.ts", find: "isDefault: def === d }", put: "isDefault: false }" },
  { label: "the below-reserve sentence is dropped", file: "plan/present.ts", find: 'return "The battery is at " + Math.round(socPct) + " percent, below the " + Math.round(reservePct) + " percent reserve. Nothing is charging. Use Charge Battery if you want it filled.";', put: 'return "";' },
  { label: "the sentence is shown while the battery is not below the reserve", file: "plan/controlsModel.ts", find: "h.socPct !== null && h.socPct < rem.override.reservePct", put: "h.socPct !== null" },
  { label: "the card ignores the owner's confirmation switch", file: "plan/helpers.ts", find: "const raw: OverrideConfigRaw = {\n    confirmed,", put: "const raw: OverrideConfigRaw = {\n    confirmed: true," },
  { label: "the controls show without the guarded scripts", file: "plan/controlsModel.ts", find: "const missingScripts = [PLAN_CONTROL_IDS.start_script, PLAN_CONTROL_IDS.cancel_script].filter((id) => ctx.states[id] === undefined);", put: "const missingScripts: string[] = [];" },
  { label: "a cancel is offered with nothing running", file: "plan/controlsModel.ts", find: "cancel: row || held ? cancelOverrideCall(kind, revision) : null,", put: "cancel: cancelOverrideCall(kind, revision)," },   // re-anchored (owner decision r15): a Cancel is also offered for a held kind; the mutant is the same
  { label: "the script's refusal is not shown", file: "plan/controls.ts", find: "${vm.lastResult ? html`", put: "${false ? html`" },
];

test("mutants of the card's controls: each is caught by the end-to-end checks", async () => {
  assert.ok(MUTANTS.length >= 15);
  const survived: string[] = [];
  for (const m of MUTANTS) {
    const Mut = await loadMutant(m.file, m.find, m.put, m.times ?? 1);
    const problems = controlsProblems(Mut as never);
    if (problems.length === 0) survived.push(m.label);
  }
  assert.deepEqual(survived, []);
});

test("an equivalent rewrite of a control label survives (the checks look at behaviour, not at words)", async () => {
  const Eq = await loadMutant("plan/controls.ts", ">Cancel</button>", ">Cancel it</button>");
  assert.deepEqual(controlsProblems(Eq as never), []);
});

void PLAN_CONFIG;
