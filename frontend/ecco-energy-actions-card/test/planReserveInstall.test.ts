import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { CURRENT_RESERVE_MAX, CURRENT_RESERVE_MIN, buildPlanSnapshot, readCurrentReserve } from "../src/plan/adapter.ts";
import { HELPER_IDS, buildPlanSnapshotWithHelpers } from "../src/plan/helpers.ts";
import { BACKEND_SENSOR_IDS, CONFIRM_TEXT, READY_GAPS_LEAD, READY_TEXT, buildControlsVM, readInstall, readPlanReserve, readinessOf, reserveVM } from "../src/plan/controlsModel.ts";
import { OVERRIDES_LINE_NONE_HELPER, OVERRIDES_STATUS_NOTE, compactSummaries, presentPlan } from "../src/plan/present.ts";
import { PLAN_CONTROL_IDS } from "../src/plan/planActions.ts";
import { clockContextFrom } from "../src/plan/clock.ts";
import { renderPlanSection } from "../src/plan/view.ts";
import { renderPlanControls } from "../src/plan/controls.ts";
import { flatten, loadCardClass } from "./support/loadCard.ts";
import { loadMutantCard } from "./support/mutantCard.ts";
import { NOW_MS, helperStates, running } from "./support/overrideFixtures.ts";
import { PLAN_CONFIG, planConfig, planStates } from "./support/planFixtures.ts";
import { GUARDED_START, scriptStates } from "./support/controlsProbe.ts";
import { RESERVE_CASES, SENSORS, reserveInstallProblems } from "./support/reserveProbe.ts";

// Corrections of the Energy Actions card (24 Nov 2026 D1 findings):
//   1. the CURRENT backup reserve (the owner's helper, read by the installed backend's rule: finite, 0 to 100) is kept apart from the override's
//      TARGET reserve (the policy value, 10 to 100, strictly above the reserve now to be offered). A reserve of 5 % is valid and shown;
//   2. "installed" is derived from what exists in Home Assistant, so the card never says the guarded start path is missing while it works;
//   3. the guarded section is compact: folded regions with one-line summaries, closed by default.

const root = resolve(import.meta.dirname, "..");
const src = (f: string): string => readFileSync(join(root, "src", f), "utf8");
const NOW_MIN = Math.floor(NOW_MS / 60000);
const cfg = (extra: Record<string, unknown> = {}, plan: Record<string, unknown> = {}): never => planConfig(extra, plan) as never;
const configured = (patch: Record<string, unknown> = {}) => helperStates(scriptStates(planStates()), patch);

let Card: Awaited<ReturnType<typeof loadCardClass>>;
before(async () => {
  Card = await loadCardClass();
});

// ---- the current reserve, by the backend's rule ------------------------------------------------------------------------------------------

test("the current reserve is read like the backend reads it: a finite number from 0 to 100, any decimal, nothing else", () => {
  assert.equal(CURRENT_RESERVE_MIN, 0);
  assert.equal(CURRENT_RESERVE_MAX, 100);
  const known: [string, number][] = [["0", 0], ["4.9", 4.9], ["5", 5], ["5.0", 5], ["9.9", 9.9], ["10", 10], ["12.5", 12.5], ["80", 80], ["100", 100], [" 7 ", 7]];
  for (const [text, n] of known) {
    const r = readCurrentReserve({ "input_number.r": { state: text } }, "input_number.r");
    assert.deepEqual({ known: r.known, value: r.value }, { known: true, value: n }, text);
  }
  for (const text of ["100.1", "-0.1", "-1", "101", "1e3", "NaN", "Infinity", "inf", "abc", "5%", "unknown", "unavailable", "", "  "]) {
    const r = readCurrentReserve({ "input_number.r": { state: text } }, "input_number.r");
    assert.equal(r.known, false, JSON.stringify(text));
    assert.equal(r.value, null);
    assert.ok(r.reason.length > 10, "a reason is given: " + JSON.stringify(text));
  }
  assert.match(readCurrentReserve({}, undefined).reason, /No backup reserve entity is configured/);
  assert.match(readCurrentReserve({}, "input_number.gone").reason, /entity was not found/);
});

test("a reserve of 5 % is a known, shown current reserve (the plan floor of 10 % applies to the plan's own intent, not to what the helper reads)", () => {
  const states = planStates();
  states[PLAN_CONFIG.reserve] = { state: "5" };
  const snap = buildPlanSnapshot(planConfig() as never, states);
  const f = snap.fields.find((x) => x.path === "reserve.backupPct");
  assert.ok(f);
  assert.equal(f.known, true);
  assert.equal(f.value, 5);
  assert.match(f.note ?? "", /accept any reserve from 0 to 100/);
  assert.deepEqual(snap.currentReserve, { known: true, value: 5, reason: "" });
  assert.equal(snap.tomorrow.reservePct.known && snap.tomorrow.reservePct.value, 5, "Tomorrow's Plan carries 5, not the model's placeholder");
  assert.ok(snap.tomorrow.why.some((w) => /Backup reserve 5 %/.test(w.text)));
  const rows = presentPlan(buildPlanSnapshotWithHelpers(planConfig() as never, states, NOW_MIN)).settings.find((s) => s.path === "reserve.backupPct");
  assert.equal(rows?.known, true);
  assert.equal(rows?.text, "5 %");
  assert.ok(!JSON.stringify(rows).includes("outside what ECCO accepts"));
  // in the plan's own range the field is exactly what it was
  states[PLAN_CONFIG.reserve] = { state: "20" };
  const same = buildPlanSnapshot(planConfig() as never, states).fields.find((x) => x.path === "reserve.backupPct");
  assert.equal(same?.value, 20);
  assert.equal(same?.note, undefined);
});

test("an unreadable or out-of-range reserve stays unknown with an honest reason and hides the control", () => {
  for (const state of ["unknown", "unavailable", "NaN", "100.1", "-3", "abc"]) {
    const states = configured();
    states[PLAN_CONFIG.reserve] = { state };
    const snap = buildPlanSnapshotWithHelpers(cfg(), states as never, NOW_MIN);
    assert.equal(snap.currentReserve.known, false, state);
    const f = snap.fields.find((x) => x.path === "reserve.backupPct");
    assert.equal(f?.known, false, state);
    assert.ok((f?.reason ?? "").length > 10);
    const vm = buildControlsVM({ snap, states: states as never, nowMs: NOW_MS, clock: clockContextFrom(NOW_MS, () => 0) });
    const k = vm?.kinds.find((x) => x.kind === "prepare_power_cut");
    assert.deepEqual(k?.choices, [], state);
    assert.ok((k?.blockedReason ?? "").length > 10, state);
    assert.match(k?.reserve?.nowText ?? "", /^Reserve now unknown \(/);
    assert.equal(k?.reserve?.canRaise, null);
    assert.ok((vm?.kinds.find((x) => x.kind === "hold_battery")?.choices.length ?? 0) > 0, "Hold battery does not depend on the reserve");
  }
});

test("both reserves are shown: 'Reserve now 5 %' and 'Power cut target 80 %'; the target is above the reserve now only when it can raise it", () => {
  const states = configured();
  states[PLAN_CONFIG.reserve] = { state: "5" };
  const snap = buildPlanSnapshotWithHelpers(cfg(), states as never, NOW_MIN);
  const vm = buildControlsVM({ snap, states: states as never, nowMs: NOW_MS, clock: clockContextFrom(NOW_MS, () => 0) });
  const k = vm?.kinds.find((x) => x.kind === "prepare_power_cut");
  assert.equal(k?.reserve?.nowText, "Reserve now 5 %");
  assert.equal(k?.reserve?.targetText, "Power cut target 80 %");
  assert.equal(k?.reserve?.canRaise, true);
  assert.ok((k?.choices.length ?? 0) > 0);
  assert.equal(vm?.kinds.find((x) => x.kind === "hold_battery")?.reserve, null);
  assert.deepEqual(reserveVM(5, "", 80, ""), { nowPct: 5, nowReason: "", targetPct: 80, targetReason: "", planPct: null, planReason: "", nowText: "Reserve now 5 %", targetText: "Power cut target 80 %", planText: null, canRaise: true });
  assert.equal(reserveVM(80, "", 80, "").canRaise, false);
  assert.equal(reserveVM(null, "x", 80, "").canRaise, null);
  assert.match(flatten(renderPlanSection(cfg(), states as never, NOW_MS, renderPlanControls(() => undefined))), /Reserve now 5 %<\/span> &middot; <span data-reserve-target>Power cut target 80 %/);
});

test("the owner's reserve and the reserve ECCO's plan uses are labelled apart ('Your reserve', 'Plan reserve now') whenever the plan's can differ", () => {
  // with the plan's reserve given, the owner's figure is 'Your reserve' and the plan's stands beside it; without it, the plain 'Reserve now' stays
  assert.deepEqual(reserveVM(5, "", 80, "", { known: true, value: 80, reason: "" }), { nowPct: 5, nowReason: "", targetPct: 80, targetReason: "", planPct: 80, planReason: "", nowText: "Your reserve 5 %", targetText: "Power cut target 80 %", planText: "Plan reserve now 80 %", canRaise: true });
  const unknownPlan = reserveVM(5, "", 80, "", { known: false, value: null, reason: "the effective-reserve sensor was not found" });
  assert.equal(unknownPlan.planText, "Plan reserve now unknown (the effective-reserve sensor was not found)");
  assert.equal(unknownPlan.planPct, null);
  assert.equal(unknownPlan.nowText, "Your reserve 5 %");
  assert.equal(reserveVM(null, "x", 80, "", { known: true, value: 80, reason: "" }).nowText, "Your reserve unknown (x)");
  assert.equal(reserveVM(5, "", 80, "", null).planText, null);
  // the plan's own reserve reading follows the installed sensor's rule: a whole percent from 0 to 100, anything else is unknown
  const read = (state: string | undefined) => readPlanReserve(state === undefined ? {} : { [BACKEND_SENSOR_IDS.effective_reserve]: { state } });
  assert.deepEqual(read("80"), { known: true, value: 80, reason: "" });
  assert.deepEqual(read("0"), { known: true, value: 0, reason: "" });
  assert.deepEqual(read("100"), { known: true, value: 100, reason: "" });
  for (const bad of ["101", "100.5", "-1", "150", "abc", "NaN", "1e3"]) assert.equal(read(bad).known, false, bad);
  for (const dead of ["unknown", "unavailable", ""]) assert.match(read(dead).reason, /cannot be read/, dead);
  assert.match(read(undefined).reason, /was not found/);
  assert.match(read("150").reason, /does not read a percentage from 0 to 100/);
});

test("a target must be above the owner's reserve rounded UP (the installed sensor rounds it up: 79.5 is published as 80), so 79.5 against 80 raises nothing and is not offered", () => {
  assert.equal(reserveVM(79.5, "", 80, "").canRaise, false);
  assert.equal(reserveVM(79.01, "", 80, "").canRaise, false);
  assert.equal(reserveVM(79, "", 80, "").canRaise, true);
  assert.equal(reserveVM(9.9, "", 10, "").canRaise, false);
  assert.equal(reserveVM(99.9, "", 100, "").canRaise, false);
  assert.equal(reserveVM(4.9, "", 80, "").canRaise, true);
  const states = configured();
  states[PLAN_CONFIG.reserve] = { state: "79.5" };
  states[SENSORS.effective_reserve] = { state: "80" };
  const snap = buildPlanSnapshotWithHelpers(cfg(), states as never, NOW_MIN);
  const vm = buildControlsVM({ snap, states: states as never, nowMs: NOW_MS, clock: clockContextFrom(NOW_MS, () => 0) });
  const k = vm?.kinds.find((x) => x.kind === "prepare_power_cut");
  assert.deepEqual(k?.choices, []);
  assert.equal(k?.blockedReason, "The power cut target (80 %) is not above the reserve now (79.5 %, which the plan uses as 80 %), so it cannot raise the reserve.");
  assert.equal(k?.reserve?.nowText, "Your reserve 79.5 %", "the plan's own figure (80) differs from the owner's, so both are labelled");
  assert.equal(k?.reserve?.planText, "Plan reserve now 80 %");
  assert.equal(k?.reserve?.canRaise, false);
  assert.ok((vm?.kinds.find((x) => x.kind === "hold_battery")?.choices.length ?? 0) > 0, "Hold battery does not depend on the reserve");
  assert.ok((vm?.kinds.find((x) => x.kind === "skip_tonight")?.choices.length ?? 0) > 0, "Skip tonight does not depend on the reserve");
});

test("the reserve table of the card end to end: 0, 4.9, 5, 9.9, 10, 80, 100, 100.1, NaN, unknown, unavailable against target 80, and the target's own floor", () => {
  assert.ok(RESERVE_CASES.length >= 16);
  for (const c of ["0", "4.9", "5", "9.9", "10", "79", "79.5", "79.9", "80", "100", "100.01", "100.05", "100.1", "NaN", "unknown", "unavailable"]) assert.ok(RESERVE_CASES.some((x) => x.state === c), c);
  assert.deepEqual(reserveInstallProblems(Card as never), []);
});

test("a target equal to the reserve now is not offered (the card is stricter than the installed script, which accepts it; nothing is raised)", () => {
  const states = configured();
  states[PLAN_CONFIG.reserve] = { state: "80" };
  const snap = buildPlanSnapshotWithHelpers(cfg(), states as never, NOW_MIN);
  assert.equal(snap.helpers?.policy.ok, true, "the policy itself still accepts an equal target, as before");
  const vm = buildControlsVM({ snap, states: states as never, nowMs: NOW_MS, clock: clockContextFrom(NOW_MS, () => 0) });
  const k = vm?.kinds.find((x) => x.kind === "prepare_power_cut");
  assert.deepEqual(k?.choices, []);
  assert.match(k?.blockedReason ?? "", /not above the reserve now \(80 %\), so it cannot raise the reserve/);
});

// ---- installed means: it exists in Home Assistant -------------------------------------------------------------------------------------------

test("installed is read from the entities that exist: the two plan scripts, the confirmation switch, the two plan sensors and the guarded Dump start", () => {
  const empty = readInstall({}, null);
  assert.deepEqual(empty, { startScript: false, cancelScript: false, confirmationSwitch: false, effectiveReserve: false, exportHold: false, guardedDump: "not_configured", missing: [PLAN_CONTROL_IDS.start_script, PLAN_CONTROL_IDS.cancel_script, HELPER_IDS.confirmed, BACKEND_SENSOR_IDS.effective_reserve, BACKEND_SENSOR_IDS.export_hold] });
  const all = {
    [PLAN_CONTROL_IDS.start_script]: { state: "off" }, [PLAN_CONTROL_IDS.cancel_script]: { state: "off" }, [HELPER_IDS.confirmed]: { state: "on" },
    [SENSORS.effective_reserve]: { state: "5" }, [SENSORS.export_hold]: { state: "clear" }, [GUARDED_START]: { state: "off" },
  };
  assert.deepEqual(readInstall(all, GUARDED_START), { startScript: true, cancelScript: true, confirmationSwitch: true, effectiveReserve: true, exportHold: true, guardedDump: "installed", missing: [] });
  assert.equal(readInstall({}, GUARDED_START).guardedDump, "missing");
  assert.ok(readInstall({}, GUARDED_START).missing.includes(GUARDED_START));
  assert.equal(readInstall(all, "").guardedDump, "not_configured");
  assert.equal(readInstall(all, undefined).guardedDump, "not_configured");
  // the entity exists even when its state is unavailable: that is not 'not installed'
  assert.equal(readInstall({ [PLAN_CONTROL_IDS.start_script]: { state: "unavailable" } }, null).startScript, true);
});

test("the readiness status: 'Overrides ready.', the confirmation message, or 'not installed' only when the scripts are really absent", () => {
  const all = readInstall({ [PLAN_CONTROL_IDS.start_script]: { state: "off" }, [PLAN_CONTROL_IDS.cancel_script]: { state: "off" }, [HELPER_IDS.confirmed]: { state: "on" }, [SENSORS.effective_reserve]: { state: "5" }, [SENSORS.export_hold]: { state: "clear" } }, null);
  assert.deepEqual(readinessOf(all, true, { ok: true }, null), { kind: "ready", text: READY_TEXT });
  assert.equal(READY_TEXT, "Overrides ready.");
  assert.deepEqual(readinessOf(all, false, { ok: false, reasons: ["The owner has not confirmed"] }, null), { kind: "needs_confirmation", text: CONFIRM_TEXT });
  assert.equal(CONFIRM_TEXT, "Turn on the confirmation switch: override limits reviewed and confirmed.");
  assert.equal(readinessOf(all, null, { ok: false }, null).kind, "confirmation_unreadable");
  const unusable = readinessOf(all, true, { ok: false, reasons: ["Hold battery default is longer than its maximum."] }, null);
  assert.equal(unusable.kind, "limits_unusable");
  assert.match(unusable.text, /Hold battery default is longer than its maximum\./);
  const none = readInstall({}, null);
  assert.equal(readinessOf(none, true, { ok: true }, null).kind, "not_installed");
  assert.match(readinessOf(none, true, { ok: true }, null).text, /not installed/);
  const onlyCancel = readInstall({ [PLAN_CONTROL_IDS.cancel_script]: { state: "off" } }, null);
  assert.equal(readinessOf(onlyCancel, true, { ok: true }, null).kind, "partial");
  assert.match(readinessOf(onlyCancel, true, { ok: true }, null).text, /ecco_plan_override_start was not found/);
  assert.ok(!/not installed/i.test(readinessOf(onlyCancel, true, { ok: true }, null).text), "'not installed' is said only when BOTH guarded scripts are absent");
  const onlyStart = readInstall({ [PLAN_CONTROL_IDS.start_script]: { state: "off" } }, null);
  assert.equal(readinessOf(onlyStart, true, { ok: true }, null).kind, "partial");
  assert.equal(readinessOf(onlyStart, true, { ok: true }, null).text, "Only part of the override package is installed: " + PLAN_CONTROL_IDS.cancel_script + " was not found, so overrides cannot be started or cancelled here.");
  for (const ok of [readinessOf(all, true, { ok: true }, null), readinessOf(all, false, { ok: false }, null)]) assert.ok(!/not installed/i.test(ok.text));
  // a missing plan sensor or guarded Dump start is a gap: a start can be sent, but 'Overrides ready.' is not said
  const lacking = readInstall({ [PLAN_CONTROL_IDS.start_script]: { state: "off" }, [PLAN_CONTROL_IDS.cancel_script]: { state: "off" } }, GUARDED_START);
  assert.deepEqual(readinessOf(lacking, true, { ok: true }, null), { kind: "ready_with_gaps", text: "Overrides only partly ready. Not found: the effective-reserve sensor, the export-hold sensor, the guarded Dump to Grid start script." });
  assert.equal(READY_GAPS_LEAD, "Overrides only partly ready.");
  assert.ok(!readinessOf(lacking, true, { ok: true }, null).text.includes(READY_TEXT));
  const noSensors = readInstall({ [PLAN_CONTROL_IDS.start_script]: { state: "off" }, [PLAN_CONTROL_IDS.cancel_script]: { state: "off" } }, null);
  assert.equal(readinessOf(noSensors, true, { ok: true }, null).text, "Overrides only partly ready. Not found: the effective-reserve sensor, the export-hold sensor.");
  // an unreadable plan revision: the installed start script refuses every start, so the status says so (after the switch and the limits, which come first)
  assert.deepEqual(readinessOf(all, true, { ok: true }, "The stored plan revision cannot be read."), { kind: "revision_unreadable", text: "The stored plan revision cannot be read, so no override can be started." });
  assert.equal(readinessOf(all, true, { ok: true }, "The stored plan revision is not a whole number.").text, "The stored plan revision is not a whole number, so no override can be started.");
  assert.equal(readinessOf(lacking, true, { ok: true }, "The stored plan revision cannot be read.").kind, "revision_unreadable", "the revision outranks the gaps");
  assert.equal(readinessOf(all, false, { ok: false }, "The stored plan revision cannot be read.").kind, "needs_confirmation", "the switch comes first");
  assert.equal(readinessOf(all, true, { ok: false, reasons: ["x"] }, "The stored plan revision cannot be read.").kind, "limits_unusable", "the limits come first");
  assert.equal(readinessOf(none, true, { ok: true }, "The stored plan revision cannot be read.").kind, "not_installed", "the missing scripts come first");
});

test("the stale 'guarded start path ... not installed' line is gone: the none-active line says only what is true, whether or not the scripts exist", () => {
  assert.equal(OVERRIDES_LINE_NONE_HELPER, "Quick overrides: none active.");
  for (const states of [configured(), helperStates(planStates())]) {
    const line = presentPlan(buildPlanSnapshotWithHelpers(cfg(), states as never, NOW_MIN)).overridesLine;
    assert.equal(line, OVERRIDES_LINE_NONE_HELPER);
    assert.ok(!/guarded start path|not installed|needs/i.test(line));
  }
  for (const f of ["plan/present.ts", "plan/view.ts", "plan/controls.ts", "plan/controlsModel.ts"]) {
    assert.ok(!src(f).includes("which is not installed"), f);
    assert.ok(!src(f).includes("needs the guarded start path"), f);
  }
});

test("the rendered section tells the truth about the installed overrides (ready, switch off, scripts absent)", () => {
  const render = (states: Record<string, unknown>, extra: Record<string, unknown> = {}): string => flatten(renderPlanSection(cfg(extra), states as never, NOW_MS, renderPlanControls(() => undefined)));
  const sensors = { [SENSORS.effective_reserve]: { state: "20" }, [SENSORS.export_hold]: { state: "clear" } };
  const ready = render(configured(sensors));
  assert.ok(ready.includes('data-readiness=ready role="status">Overrides ready.'));
  assert.ok(!/starting one needs|which is not installed/.test(ready));
  // the two plan sensors absent: not 'Overrides ready.' (a warning-coloured ready-with-gaps status instead)
  const gaps = render(configured());
  assert.ok(gaps.includes('data-readiness=ready_with_gaps role="status">Overrides only partly ready. Not found: the effective-reserve sensor, the export-hold sensor.'));
  assert.ok(!gaps.includes("Overrides ready."));
  // the plan revision unreadable: the start script refuses every start, so not 'Overrides ready.' either
  const norev = render(configured({ ...sensors, [HELPER_IDS.revision]: { state: "unavailable" } }));
  assert.ok(norev.includes('data-readiness=revision_unreadable role="status">The stored plan revision cannot be read, so no override can be started.'));
  assert.ok(!norev.includes("Overrides ready."));
  // the warning colour of both new kinds
  const css = src("plan/controls.ts");
  assert.ok(/\.plan-readiness\[data-readiness="ready_with_gaps"\],\s*\.plan-readiness\[data-readiness="revision_unreadable"\] \{\s*color: var\(--eaa-warning\);/.test(css), "ready_with_gaps and revision_unreadable are warning-coloured");
  const off = render(configured({ [HELPER_IDS.confirmed]: { state: "off" } }));
  assert.ok(off.includes("Turn on the confirmation switch: override limits reviewed and confirmed."));
  const absent = render(helperStates(planStates()));
  assert.ok(absent.includes("The guarded scripts were not found") && absent.includes("not installed here"));
  assert.ok(absent.includes("data-controls-missing data-readiness=not_installed") && !absent.includes("data-readiness=ready"));
  // one script absent: the status text names it; it is not 'not installed' (that is said only when both are absent)
  for (const gone of [PLAN_CONTROL_IDS.start_script, PLAN_CONTROL_IDS.cancel_script]) {
    const part = render(configured({ [gone]: undefined }));
    assert.ok(part.includes("data-controls-missing data-readiness=partial>Only part of the override package is installed: " + gone + " was not found, so overrides cannot be started or cancelled here."), gone);
    assert.ok(!/not installed|guarded scripts were not found/.test(part.replace(/Partial protection only[^<]*/, "")), gone);
    assert.ok(!part.includes("data-choice=") && !part.includes('class="plan-readiness"'), gone);
  }
});

test("the guarded view no longer says 'Status only' next to working Start and Cancel; the view without controls still does", () => {
  const states = running(configured(), "hold_battery", 40, 200);
  const guarded = flatten(renderPlanSection(cfg(), states as never, NOW_MS, renderPlanControls(() => undefined)));
  assert.ok(!guarded.includes("Status only:") && !guarded.includes("nothing in this view starts, cancels or enforces an override"));
  assert.ok(guarded.includes('data-records-note>This list only shows the records Home Assistant holds: nothing in it starts, cancels or enforces an override. Start and Cancel are under Quick overrides.'));
  const idle = flatten(renderPlanSection(cfg(), configured() as never, NOW_MS, renderPlanControls(() => undefined)));
  assert.ok(!idle.includes("data-records-note") && !idle.includes("Status only:"), "no record: no note at all in the guarded view");
  // the read-only views keep their exact lines: helpers read but no controls offered (stage-2 status-only view), and no helpers at all (the goldens)
  const statusOnly = flatten(renderPlanSection(cfg(), states as never, NOW_MS));
  assert.ok(statusOnly.includes(OVERRIDES_STATUS_NOTE) && !statusOnly.includes("data-records-note"));
  assert.ok(OVERRIDES_STATUS_NOTE.startsWith("Status only: nothing in this view starts, cancels or enforces an override."));
  const noHelpers = flatten(renderPlanSection(cfg(), planStates() as never, NOW_MS, renderPlanControls(() => undefined)));
  assert.ok(!noHelpers.includes("Status only:") && !noHelpers.includes("data-records-note"));
});

// ---- the compact layout -----------------------------------------------------------------------------------------------------------------------

test("the guarded section is compact: folded regions with one-line summaries, closed by default, the limitation and the start controls visible", () => {
  const text = flatten(renderPlanSection(cfg(), configured() as never, NOW_MS, renderPlanControls(() => undefined)));
  assert.ok(text.includes("plan-section plan-compact"));
  for (const f of ["tomorrow", "limits", "tou"]) {
    assert.ok(text.includes('data-fold="' + f + '"'), f);
    assert.ok(new RegExp('data-summary="' + f + '">[^<]+<').test(text), "summary " + f);
  }
  assert.ok(!/<details[^>]*\sopen[\s>=]/.test(text), "no fold is open by default");
  const folds = (text.match(/<details/g) ?? []).length;
  assert.ok(folds >= 8, "folds: " + folds);
  // the visible (depth 0) text holds the two things that must never be folded
  const strip = (t: string): string => { let out = ""; let depth = 0; for (const part of t.split(/(<details[^>]*>|<\/details>)/)) { if (part.startsWith("<details")) depth++; else if (part === "</details>") depth--; else if (depth === 0) out += part; } return out; };
  const visible = strip(text);
  assert.ok(visible.includes("Partial protection only: the dongle's own Start button"), "the limitation sentence is visible");
  assert.ok(visible.includes("data-choice="), "the start choices are visible");
  assert.ok(!visible.includes("data-slot="), "the six slots are folded");
  assert.ok(!visible.includes('class="plan-figures"'), "the figures are folded");
  assert.ok(!visible.includes("Why?") && !visible.includes("Planned settings"), "the plan text is folded");
  // the section's static, always-visible text is short: a structural stand-in for the measured height (the harness measures pixels)
  const visibleChars = visible.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").length;
  assert.ok(visibleChars < 3000, "always-visible text is " + visibleChars + " characters");
  const expanded = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").length;
  assert.ok(expanded > visibleChars * 1.4, "the folds hold the bulk: " + expanded + " vs " + visibleChars);
});

test("the one-line summaries say what is folded", () => {
  const vm = presentPlan(buildPlanSnapshotWithHelpers(cfg(), configured() as never, NOW_MIN));
  const s = compactSummaries(vm);
  assert.equal(s.tomorrow, "Import 4.5 kWh · Export 2.2 kWh · Solar 11.4 kWh · Your reserve 20 %");
  assert.match(s.limits ?? "", /^Limits in force · .*revision 12/);
  assert.equal(s.limitsAttention, false);
  assert.equal(s.tou, vm.tou.headline);
  const nothing = compactSummaries(presentPlan(buildPlanSnapshotWithHelpers(cfg(), configured({}) as never, NOW_MIN)));
  assert.ok(nothing.tomorrow.length > 0);
  const noAdvice = presentPlan(buildPlanSnapshotWithHelpers(cfg(), helperStates(scriptStates(planStates(false))) as never, NOW_MIN));
  assert.equal(compactSummaries(noAdvice).tomorrow, "Your reserve 20 %", "known figures only, never a placeholder");
  const bad = compactSummaries(presentPlan(buildPlanSnapshotWithHelpers(cfg(), configured({ [HELPER_IDS.min_expiry]: { state: "0" } }) as never, NOW_MIN)));
  assert.match(bad.limits ?? "", /^Limits not usable/);
  assert.equal(bad.limitsAttention, true);
  assert.equal(compactSummaries(presentPlan(buildPlanSnapshot(planConfig() as never, planStates()) as never)).limits, null, "no plan helper: no limits line");
});

test("with no plan helper the read-only section keeps its former markup: no fold, no compact class", () => {
  const text = flatten(renderPlanSection(cfg(), planStates() as never, NOW_MS, renderPlanControls(() => undefined)));
  assert.ok(!text.includes("data-fold=") && !text.includes("plan-compact"));
  assert.ok(text.includes('aria-label="Plan, read only"'));
});

// ---- mutants of the new logic: each must be caught by the end-to-end probe ---------------------------------------------------------------------------

const MUTANTS: { label: string; file: string; find: string; put: string; times?: number }[] = [
  { label: "the plan's 10 % floor is applied to the reserve now again", file: "plan/adapter.ts", find: "export const CURRENT_RESERVE_MIN = 0;", put: "export const CURRENT_RESERVE_MIN = 10;" },
  { label: "a reserve above 100 is accepted", file: "plan/adapter.ts", find: "n < CURRENT_RESERVE_MIN || n > CURRENT_RESERVE_MAX", put: "n < CURRENT_RESERVE_MIN" },
  { label: "a negative reserve is accepted", file: "plan/adapter.ts", find: "n < CURRENT_RESERVE_MIN || n > CURRENT_RESERVE_MAX", put: "n > CURRENT_RESERVE_MAX" },
  { label: "a missing reserve entity is reported as unreadable", file: "plan/adapter.ts", find: 'if (!id) return { known: false, value: null, reason: "No backup reserve entity is configured (plan.reserve)." };', put: "" },
  { label: "the reserve is never known (the old floor path for every value)", file: "plan/adapter.ts", find: "raw[\"reserve.backupPct\"] = currentReserve.known\n    ? checked(", put: "raw[\"reserve.backupPct\"] = false\n    ? checked(" },
  { label: "a reserve outside the plan model is not carried by the field", file: "plan/adapter.ts", find: 'if (p === "reserve.backupPct" && r.value === null && currentReserve.known && currentReserve.value !== null) {', put: "if (false) {" },
  { label: "the field shows the model's placeholder instead of the reserve now", file: "plan/adapter.ts", find: "        known: true,\n        value: currentReserve.value,", put: "        known: true,\n        value: rec.value," },
  { label: "Tomorrow's Plan keeps the model's placeholder reserve", file: "plan/adapter.ts", find: "? { ...t.reservePct, value: (reserveField as FieldInfo).value }", put: "? t.reservePct" },
  { label: "an equal target is offered", file: "plan/controlsModel.ts", find: "reservePair.canRaise === false) {", put: "false) {" },
  { label: "every target is blocked", file: "plan/controlsModel.ts", find: "reservePair.canRaise === false) {", put: "reservePair.canRaise !== null) {" },
  { label: "the reserve now is not labelled", file: "plan/controlsModel.ts", find: 'const label = plan !== null ? "Your reserve" : "Reserve now";', put: 'const label = plan !== null ? "Your reserve" : "Reserve";' },
  { label: "the power cut target is not labelled", file: "plan/controlsModel.ts", find: '"Power cut target " + targetPct + " %"', put: '"Target " + targetPct + " %"' },
  { label: "an unknown reserve is not called unknown", file: "plan/controlsModel.ts", find: 'label + " unknown (" + nowReason + ")"', put: 'label + " 0 %"' },
  // ---- the five minors of the independent review (25 Nov 2026) ----
  { label: "a reserve of 100.01 is accepted (anything from 100 to 100.05)", file: "plan/adapter.ts", find: "n < CURRENT_RESERVE_MIN || n > CURRENT_RESERVE_MAX", put: "n < CURRENT_RESERVE_MIN || n > CURRENT_RESERVE_MAX + 0.05" },
  { label: "the status is ready when only the cancel script is missing", file: "plan/controlsModel.ts", find: "if (!install.startScript || !install.cancelScript) {", put: "if (!install.startScript) {" },
  { label: "the status follows the reserve-aware policy, not the start limits", file: "plan/controlsModel.ts", find: "h.startPolicy.ok ? { ok: true } : { ok: false, reasons: h.startPolicy.reasons }, h.revision.known", put: "h.policy.ok ? { ok: true } : { ok: false, reasons: h.policy.reasons }, h.revision.known" },
  { label: "the owner's raw reserve is compared with the target, not the rounded-up one (79.5 against 80 is offered)", file: "plan/controlsModel.ts", find: "targetPct > Math.ceil(nowPct)", put: "targetPct > nowPct" },
  { label: "'Overrides ready.' is said although something was not found", file: "plan/controlsModel.ts", find: 'return gaps.length ? { kind: "ready_with_gaps", text: READY_GAPS_LEAD + " Not found: " + gaps.join(", ") + "." } : { kind: "ready", text: READY_TEXT };', put: 'return { kind: "ready", text: gaps.length ? READY_TEXT + " Not found: " + gaps.join(", ") + "." : READY_TEXT };' },
  { label: "an unreadable plan revision is not said", file: "plan/controlsModel.ts", find: "if (revisionReason !== null) return {", put: "if (false) return {" },
  { label: "the plan revision is read as always readable", file: "plan/controlsModel.ts", find: "h.revision.known ? null : h.revision.reason", put: "null" },
  { label: "the status text of one missing script is the generic not-installed sentence", file: "plan/controls.ts", find: 'vm.readiness.kind === "partial" ? vm.readiness.text : ', put: 'false ? vm.readiness.text : ' },
  { label: "the plan's reserve is not shown while an override record is held", file: "plan/controlsModel.ts", find: "const showPlanReserve = h.active.length > 0 || h.held.length > 0 || (", put: "const showPlanReserve = (" },
  { label: "the plan's reserve is always shown", file: "plan/controlsModel.ts", find: "const showPlanReserve = h.active.length > 0 || h.held.length > 0 || (planRead.known && (currentReservePct === null || planRead.value !== currentReservePct));", put: "const showPlanReserve = true;" },
  { label: "the plan's reserve is not shown when it differs from the owner's with nothing running", file: "plan/controlsModel.ts", find: "|| (planRead.known && (currentReservePct === null || planRead.value !== currentReservePct));", put: ";" },
  { label: "the owner's reserve keeps the label 'Reserve now' beside the plan's", file: "plan/controlsModel.ts", find: 'const label = plan !== null ? "Your reserve" : "Reserve now";', put: 'const label = "Reserve now";' },
  { label: "the plan's reserve is not labelled as the plan's", file: "plan/controlsModel.ts", find: '"Plan reserve now " + plan.value + " %"', put: '"Reserve now " + plan.value + " %"' },
  { label: "an unreadable plan reserve is not called unknown", file: "plan/controlsModel.ts", find: '"Plan reserve now unknown (" + plan.reason + ")"', put: '"Plan reserve now 0 %"' },
  { label: "a plan reserve outside 0 to 100 is taken as a figure", file: "plan/controlsModel.ts", find: "if (n === null || n < CURRENT_RESERVE_MIN || n > CURRENT_RESERVE_MAX) return {", put: "if (n === null) return {" },
  { label: "an unreadable plan reserve sensor is not told apart from a wrong one", file: "plan/controlsModel.ts", find: 'if (stateText(states, id) === null) return { known: false, value: null, reason: "the effective-reserve sensor cannot be read" };', put: "" },
  { label: "the Tomorrow's Plan summary says a bare 'Reserve'", file: "plan/present.ts", find: 'reserve: "Your reserve" }', put: 'reserve: "Reserve" }' },
  { label: "the reserve figure inside the Tomorrow's Plan fold keeps the bare label", file: "plan/view.ts", find: 'figure(f.key === "reserve" ? { ...f, label: "Your reserve" } : f)', put: "figure(f)" },
  { label: "the stale 'Status only' line is back in the guarded view", file: "plan/view.ts", find: "${overrideBlock(vm.overrideBlock, true)}", put: "${overrideBlock(vm.overrideBlock)}" },
  { label: "the stale 'Status only' line is kept beside the records note", file: "plan/view.ts", find: "${compact ? nothing : html`", put: "${false ? nothing : html`" },
  { label: "the records note is dropped", file: "plan/view.ts", find: "${compact && (b.rows.length || b.held.length) ? html`", put: "${false ? html`" },
  { label: "the records note is shown when there is no record", file: "plan/view.ts", find: "${compact && (b.rows.length || b.held.length) ? html`", put: "${compact ? html`" },
  { label: "the switch being off is not said", file: "plan/controlsModel.ts", find: 'if (confirmed === false) return { kind: "needs_confirmation", text: CONFIRM_TEXT };', put: "" },
  { label: "the switch is read as always on", file: "plan/controlsModel.ts", find: "readinessOf(install, h.confirmed,", put: "readinessOf(install, true," },
  { label: "absent scripts are not called not installed", file: "plan/controlsModel.ts", find: "if (!install.startScript && !install.cancelScript) {", put: "if (false) {" },
  { label: "one missing script is not said", file: "plan/controlsModel.ts", find: "if (!install.startScript || !install.cancelScript) {", put: "if (!install.startScript && !install.cancelScript) {" },
  { label: "the start script is assumed to exist", file: "plan/controlsModel.ts", find: "const startScript = has(PLAN_CONTROL_IDS.start_script);", put: "const startScript = true;" },
  { label: "the guarded Dump start is assumed to exist", file: "plan/controlsModel.ts", find: 'has(guardedId) ? "installed" : "missing"', put: '"installed"' },
  { label: "a missing plan sensor is not said", file: "plan/controlsModel.ts", find: 'if (!install.effectiveReserve) gaps.push("the effective-reserve sensor");', put: "" },
  { label: "a missing export-hold sensor is not said", file: "plan/controlsModel.ts", find: 'if (!install.exportHold) gaps.push("the export-hold sensor");', put: "" },
  { label: "the card's guarded start id is not passed to the readiness check", file: "plan/view.ts", find: 'guardedStart: typeof guardedStart === "string" ? guardedStart : null', put: "guardedStart: null" },
  { label: "the stale message is back", file: "plan/present.ts", find: 'export const OVERRIDES_LINE_NONE_HELPER = "Quick overrides: none active.";', put: 'export const OVERRIDES_LINE_NONE_HELPER = "Quick overrides: none active. Shown as status only; starting one needs the guarded start path, which is not installed.";' },
  { label: "the status line above the controls is dropped", file: "plan/controls.ts", find: '${vm.readiness.kind !== "not_installed" && vm.readiness.kind !== "partial" ?', put: "${false ?" },
  { label: "the reserve line is dropped", file: "plan/controls.ts", find: "${k.reserve\n        ? html`<p", put: "${false\n        ? html`<p" },
  { label: "the guarded section is no longer compact", file: "plan/view.ts", find: "${planBodyCompact(vm, controls, compactSummaries(vm))}", put: "${planBody(vm, controls, true)}" },
  { label: "the Tomorrow's Plan fold opens by default", file: "plan/view.ts", find: '<details class="plan-why plan-fold" data-fold="tomorrow">', put: '<details class="plan-why plan-fold" data-fold="tomorrow" open>' },
  { label: "the TOU timeline fold opens by default", file: "plan/view.ts", find: '<details class="plan-why plan-fold" data-fold="tou">', put: '<details class="plan-why plan-fold" data-fold="tou" open>' },
  { label: "the limitation sentence is folded away", file: "plan/controls.ts", find: '      <p class="plan-reason plan-limitation" data-plan-limitation role="note">${START_BUTTON_LIMITATION}</p>\n', put: '      <details><summary>Limitation</summary><p class="plan-reason plan-limitation" data-plan-limitation role="note">${START_BUTTON_LIMITATION}</p></details>\n' },
  { label: "a reserve above the target makes every limit look unusable", file: "plan/present.ts", find: "policyOk: policy.ok || onlyReserve,", put: "policyOk: policy.ok," },
  { label: "a reserve above the target says no override can be started", file: "plan/present.ts", find: "      : h.startPolicy.ok\n        ? limitsLine(h.startPolicy.config)", put: "      : false\n        ? limitsLine(h.startPolicy.config)" },
  { label: "the summary lines are empty", file: "plan/present.ts", find: 'const tomorrow = parts.length > 0 ? parts.join(" \\u00b7 ") : (vm.adviceNote ?? "No figures yet.");', put: 'const tomorrow = "";' },
  { label: "the limits summary is dropped", file: "plan/present.ts", find: 'limits = bits.join(" \\u00b7 ");', put: 'limits = "";' },
];

test("mutants of the new logic: at least 20, each caught by the end-to-end probe", async () => {
  assert.ok(MUTANTS.length >= 20, "mutants: " + MUTANTS.length);
  assert.deepEqual(reserveInstallProblems(Card as never), [], "the unmutated card passes");
  const survived: string[] = [];
  for (const m of MUTANTS) {
    const Mut = await loadMutantCard(m.file, m.find, m.put, m.times ?? 1);
    if (reserveInstallProblems(Mut as never).length === 0) survived.push(m.label);
  }
  assert.deepEqual(survived, []);
});

test("an equivalent rewrite of a label survives (the probe looks at behaviour, not at spacing)", async () => {
  const Eq = await loadMutantCard("plan/controls.ts", "What quick overrides do", "What quick overrides do here");
  assert.deepEqual(reserveInstallProblems(Eq as never), []);
});
