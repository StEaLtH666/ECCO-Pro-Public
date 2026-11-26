import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import * as Helpers from "../src/plan/helpers.ts";
import * as Model from "../src/plan/controlsModel.ts";
import { cancelOverrideCall, isPlanServiceCall, PLAN_CONTROL_IDS, startOverrideCall } from "../src/plan/planActions.ts";
import { OVERRIDES_LINE_NONE_HELPER, presentPlan } from "../src/plan/present.ts";
import { renderPlanSection } from "../src/plan/view.ts";
import { renderPlanControls } from "../src/plan/controls.ts";
import { BASE_CONFIG } from "./support/fixtures.ts";
import type { States } from "./support/fixtures.ts";
import { flatten, loadCardClass } from "./support/loadCard.ts";
import { handlersOf, scriptStates } from "./support/controlsProbe.ts";
import { loadFreshCard, loadMutantCard } from "./support/mutantCard.ts";
import type { CardCtor } from "./support/mutantCard.ts";
import { EPOCH_ID, KIND_NAMES, MIN, NEVER, NOW_MIN, NOW_MS, helperStates, running, setEpoch, stamp } from "./support/overrideFixtures.ts";
import type { KindName } from "./support/overrideFixtures.ts";
import { planConfig, planStates } from "./support/planFixtures.ts";

// Owner decision r15 (19 Nov 2026), known limitation 23: the card could not cancel an override that the backend still holds only through its absolute
// epoch record (or whose record it cannot read). The backend reads each kind's expiry twice, RAISE-ONLY (home-assistant/packages/ecco_plan_helpers.yaml:
// the date-and-time helper's `timestamp` attribute and an input_number in epoch seconds): a kind is ACTIVE while ANY valid source is in the future, UNREADABLE
// when either source is invalid and none holds, and CLEARED only when every source is readable and none is in the future. The card mirrors that read rule
// (pure, no clock, no write) and offers the SAME guarded Cancel for an active or unreadable kind, then reads back the revision and BOTH records.
// What is modelled here is offline only: nothing in this file was seen in a browser or on a real Home Assistant.

let Card: CardCtor;
before(async () => {
  Card = (await loadCardClass()) as unknown as CardCtor;
});

const cfg = (): never => planConfig() as never;
const configured = (patch: Record<string, unknown> = {}): States => helperStates(scriptStates(planStates()), patch);
const A_ID = (kind: KindName): string => Helpers.HELPER_IDS[(kind + "_expires") as keyof typeof Helpers.HELPER_IDS];
const S_ID = (kind: KindName): string => Helpers.HELPER_IDS[(kind + "_start") as keyof typeof Helpers.HELPER_IDS];
const LABEL: Record<KindName, string> = { hold_battery: "Hold battery", skip_tonight: "Skip tonight", prepare_power_cut: "Prepare for power cut" };
const RESERVE = (k: KindName): number | undefined => (k === "prepare_power_cut" ? 80 : undefined);
const utc = (ms: number): string => new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
const snapOf = (states: States, nowMin: number | null = NOW_MIN) => Helpers.buildPlanSnapshotWithHelpers(cfg(), states as never, nowMin);
const helpersOf = (states: States) => {
  const h = snapOf(states).helpers;
  assert.ok(h);
  return h;
};
const recOf = (states: States, kind: KindName) => {
  const r = helpersOf(states).records.find((x) => x.kind === kind);
  assert.ok(r, "a record for " + kind);
  return r;
};
const vmOf = (states: States, cancels: Model.CancelLedger = {}) => {
  const snap = snapOf(states);
  const vm = Model.buildControlsVM({ snap, states: states as never, nowMs: NOW_MS, clock: null, cancels });
  assert.ok(vm);
  return vm;
};
const kindVm = (states: States, kind: KindName, cancels: Model.CancelLedger = {}) => {
  const k = vmOf(states, cancels).kinds.find((x) => x.kind === kind);
  assert.ok(k);
  return k;
};

/** A kind that only the absolute record holds: a start record, the date-and-time expiry as given, the epoch record `endsInMin` ahead. */
function epochOnly(kind: KindName, endsInMin: number, dateTime: unknown = NEVER): States {
  const s = configured();
  running(s, kind, 30, endsInMin, RESERVE(kind));
  (s as Record<string, unknown>)[A_ID(kind)] = dateTime;
  setEpoch(s, kind, NOW_MS + endsInMin * MIN);
  return s;
}

/** The other states the backend can leave a kind in, by the epoch record's state text (the date-and-time record is cleared). */
function withEpochText(kind: KindName, text: string | undefined): States {
  const s = configured();
  running(s, kind, 30, 0, RESERVE(kind));
  (s as Record<string, unknown>)[A_ID(kind)] = NEVER;
  setEpoch(s, kind, text);
  return s;
}

// ---- 1. the absolute record alone holds the kind: a row and a Cancel -----------------------------------------------------------------------------------

test("a kind held only by the absolute record shows as an active override with the guarded Cancel (every kind, date-and-time record past, ended, unreadable or missing)", () => {
  const variants: [string, unknown][] = [
    ["ended long ago", NEVER],
    ["ended ten minutes ago", stamp(NOW_MS - 10 * MIN)],
    ["ended this minute", stamp(NOW_MS)],
    ["unavailable", { state: "unavailable" }],
    ["missing entity", undefined],
  ];
  for (const kind of KIND_NAMES) {
    for (const [what, dt] of variants) {
      const s = epochOnly(kind, 100, dt);
      if (dt === undefined) delete (s as Record<string, unknown>)[A_ID(kind)];
      const h = helpersOf(s);
      const row = h.active.find((r) => r.override.kind === kind);
      assert.ok(row, kind + " / " + what + ": a row");
      assert.equal(row.expiresText, utc(NOW_MS + 100 * MIN), kind + " / " + what + ": the instant of the absolute record, in UTC");
      assert.equal(row.remainingMin, 100);
      assert.match(row.note, /absolute epoch record/);
      assert.deepEqual(h.active.map((r) => r.override.kind), [kind], "only this kind");
      assert.deepEqual(snapOf(s).overrides.find((o) => o.kind === kind), { kind, startedAtMin: NOW_MIN - 30, expiresAtMin: NOW_MIN + 100, ...(kind === "prepare_power_cut" ? { reservePct: 80 } : {}) }, "the plan core is given the same record");
      const k = kindVm(s, kind);
      assert.equal(k.active, true);
      assert.equal(k.held, false);
      assert.equal(k.activeText, "Active until " + utc(NOW_MS + 100 * MIN) + " (ends in 1 h 40 min)");
      assert.deepEqual(k.cancel, cancelOverrideCall(kind, 12), kind + " / " + what + ": the one guarded cancel, with the stored revision");
      assert.match(k.note ?? "", /absolute epoch record/);
    }
  }
});

test("both records valid and equal behave exactly as before: the same row, the same texts, no note", () => {
  for (const kind of KIND_NAMES) {
    const both = running(configured(), kind, 40, 200, RESERVE(kind));
    setEpoch(both, kind, NOW_MS + 200 * MIN);
    const old = running(configured(), kind, 40, 200, RESERVE(kind)); // the epoch record stays at 0: the date-and-time record alone, as before
    assert.deepEqual(presentPlan(snapOf(both)).overrideBlock?.rows, presentPlan(snapOf(old)).overrideBlock?.rows, kind);
    assert.deepEqual(vmOf(both).kinds, vmOf(old).kinds, kind);
    const k = kindVm(both, kind);
    assert.match(k.activeText ?? "", /^Active until 2026-11-16 23:20 \(ends in 3 h 20 min\)$/);
    assert.equal(k.note, null);
    assert.deepEqual(helpersOf(both).problems, []);
  }
});

test("the later of the two valid instants wins, whichever record carries it", () => {
  for (const kind of KIND_NAMES) {
    const epochLater = running(configured(), kind, 30, 20, RESERVE(kind));
    setEpoch(epochLater, kind, NOW_MS + 100 * MIN);
    assert.equal(helpersOf(epochLater).active[0]?.remainingMin, 100, kind + ": the absolute record is later");
    assert.equal(helpersOf(epochLater).active[0]?.expiresText, utc(NOW_MS + 100 * MIN));
    const dateLater = running(configured(), kind, 30, 100, RESERVE(kind));
    setEpoch(dateLater, kind, NOW_MS + 20 * MIN);
    assert.equal(helpersOf(dateLater).active[0]?.remainingMin, 100, kind + ": the date-and-time record is later");
    assert.equal(helpersOf(dateLater).active[0]?.expiresText, "2026-11-16 21:40", "and it is shown in the helper's own local text");
    assert.equal(kindVm(dateLater, kind).note, null);
    const past = running(configured(), kind, 30, 100, RESERVE(kind));
    setEpoch(past, kind, NOW_MS - 20 * MIN);
    assert.equal(helpersOf(past).active[0]?.remainingMin, 100, kind + ": an ended absolute record never shortens it");
    assert.deepEqual(helpersOf(past).problems, []);
  }
});

// ---- 2. a record that cannot be read does not look cleared ----------------------------------------------------------------------------------------------

test("an unreadable record is shown as held by Home Assistant, with the plain-words note and the same Cancel (never as cleared)", () => {
  const bad: [string, string][] = [
    ["unavailable", "unavailable"], ["unknown", "unknown"], ["empty", ""], ["text", "abc"], ["negative", "-5"], ["beyond the year 2100", "4102444801"],
    ["not a number", "nan"], ["infinity", "inf"], ["hex", "0x10"], ["thousands separator", "1,000"],
  ];
  for (const kind of KIND_NAMES) {
    for (const [what, raw] of bad) {
      const s = withEpochText(kind, raw);
      const rec = recOf(s, kind);
      assert.equal(rec.read, "unreadable", kind + " / " + what);
      assert.equal(helpersOf(s).held.some((r) => r.kind === kind), true, kind + " / " + what + ": listed as held");
      assert.deepEqual(helpersOf(s).active, [], "not a trusted row, so not given to the plan core");
      assert.deepEqual(snapOf(s).overrides, []);
      assert.match(helpersOf(s).problems.join(" | "), /absolute expiry record/, what + ": the problem is said");
      const k = kindVm(s, kind);
      assert.equal(k.held, true);
      assert.equal(k.active, false);
      assert.equal(k.activeText, "Held by Home Assistant (a record cannot be read here)");
      assert.deepEqual(k.cancel, cancelOverrideCall(kind, 12), kind + " / " + what + ": the backend allows a cancel on an unreadable record, so the card offers it");
      assert.match(k.note ?? "", /cannot be read here/);
      assert.match(k.note ?? "", /keeps the hold, and any raised reserve, until a cancel settles it/);
      const text = flatten(renderPlanSection(cfg(), s as never, NOW_MS, renderPlanControls(() => undefined)));
      assert.ok(text.includes("Held by Home Assistant") && text.includes("data-cancel aria-label"), what + ": drawn with a Cancel");
      const line = presentPlan(snapOf(s)).overridesLine;
      assert.ok(line.startsWith(OVERRIDES_LINE_NONE_HELPER) && line.includes(LABEL[kind]), "the headline does not say none: " + line);
    }
  }
  // the date-and-time record unreadable (no timestamp, or not a date and time) with the absolute record ended: also not cleared
  for (const [what, dt] of [["unavailable", { state: "unavailable" }], ["no timestamp", { state: "2026-11-16 19:00:00" }], ["text", { state: "soon", attributes: { timestamp: NOW_MS / 1000 + 600 } }]] as const) {
    const s = configured();
    (s as Record<string, unknown>)[A_ID("hold_battery")] = dt;
    assert.equal(recOf(s, "hold_battery").read, "unreadable", what);
    assert.deepEqual(kindVm(s, "hold_battery").cancel, cancelOverrideCall("hold_battery", 12), what);
  }
});

test("a record that is readable and in the future holds the kind even while the other record cannot be read", () => {
  for (const kind of KIND_NAMES) {
    const dateOnly = running(configured(), kind, 30, 100, RESERVE(kind));
    setEpoch(dateOnly, kind, "unavailable");
    assert.equal(recOf(dateOnly, kind).read, "active", kind + ": the date-and-time record holds");
    assert.match(helpersOf(dateOnly).problems.join(" "), /absolute expiry record cannot be read/);
    assert.equal(helpersOf(dateOnly).active.length, 1);
    const epochOnlyBad = epochOnly(kind, 100, { state: "unavailable" });
    assert.equal(recOf(epochOnlyBad, kind).read, "active", kind + ": the absolute record holds");
    assert.match(helpersOf(epochOnlyBad).problems.join(" "), /expiry cannot be read/);
    assert.ok(kindVm(epochOnlyBad, kind).cancel);
    // but a readable record that has ended does not make an unreadable one "ended"
    const pastAndBad = running(configured(), kind, 30, -10, RESERVE(kind));
    setEpoch(pastAndBad, kind, "unavailable");
    assert.equal(recOf(pastAndBad, kind).read, "unreadable", kind);
  }
});

test("a malformed record that the backend still holds is not trusted by the card but is not shown as cleared either: a held row with a Cancel", () => {
  const s = running(configured(), "hold_battery", -10, 10); // starts after it expires
  const h = helpersOf(s);
  assert.deepEqual(h.active, []);
  assert.deepEqual(snapOf(s).overrides, []);
  assert.match(h.problems.join(" "), /starts at or after its expiry/);
  assert.equal(h.held.map((r) => r.kind).join(), "hold_battery");
  const k = kindVm(s, "hold_battery");
  assert.equal(k.held, true);
  assert.match(k.activeText ?? "", /^Held by Home Assistant until 2026-11-16 20:10 \(ends in 10 min\)$/);
  assert.match(k.note ?? "", /not trusted here/);
  assert.deepEqual(k.cancel, cancelOverrideCall("hold_battery", 12));
  const long = running(configured(), "hold_battery", 1, 4320 + 5); // longer than the hard ceiling
  assert.deepEqual(helpersOf(long).active, []);
  assert.deepEqual(kindVm(long, "hold_battery").cancel, cancelOverrideCall("hold_battery", 12));
});

// ---- 3. readable and ended: nothing ------------------------------------------------------------------------------------------------------------------

test("both records readable and not in the future: nothing is shown, no Cancel, whatever they say", () => {
  const pairs: [unknown, number | string][] = [
    [NEVER, 0], [stamp(NOW_MS - 10 * MIN), NOW_MS - 10 * MIN], [stamp(NOW_MS), NOW_MS], [NEVER, NOW_MS - 5 * MIN], [stamp(NOW_MS - 5 * MIN), 0],
    [stamp(NOW_MS - 600 * MIN), NOW_MS - 1 * MIN], [stamp(NOW_MS), "0"], [stamp(NOW_MS - MIN), "1e3"],
  ];
  for (const kind of KIND_NAMES) {
    for (const [dt, ep] of pairs) {
      const s = configured();
      (s as Record<string, unknown>)[A_ID(kind)] = dt;
      setEpoch(s, kind, ep);
      assert.equal(recOf(s, kind).read, "cleared", kind + " " + JSON.stringify(ep));
      assert.deepEqual(helpersOf(s).active, []);
      assert.deepEqual(helpersOf(s).held, []);
      assert.deepEqual(helpersOf(s).problems, []);
      const k = kindVm(s, kind);
      assert.equal(k.cancel, null);
      assert.equal(k.active || k.held, false);
      assert.equal(k.note, null);
      assert.equal(presentPlan(snapOf(s)).overridesLine, OVERRIDES_LINE_NONE_HELPER);
      const text = flatten(renderPlanSection(cfg(), s as never, NOW_MS, renderPlanControls(() => undefined)));
      assert.ok(!text.includes("data-cancel aria-label") && !text.includes("Held by Home Assistant"));
    }
  }
});

// ---- 4. an older package without the absolute records -------------------------------------------------------------------------------------------------

test("an older package (no absolute record): judged by the date-and-time record only, said plainly, and a cleared kind never looks active", () => {
  const old = (s: States): States => {
    for (const k of KIND_NAMES) setEpoch(s, k, undefined);
    return s;
  };
  const cleared = old(configured());
  const h = helpersOf(cleared);
  assert.deepEqual(h.missing, KIND_NAMES.map(EPOCH_ID), "the three absolute records are listed as not found");
  assert.deepEqual(h.records.map((r) => r.read), ["cleared", "cleared", "cleared"]);
  assert.deepEqual(h.active, []);
  assert.deepEqual(h.held, []);
  assert.match(h.problems.join(" | "), /absolute expiry record of Hold battery, Skip tonight, Prepare for power cut is not installed/);
  assert.match(h.problems.join(" | "), /judged by the date-and-time record only/);
  assert.ok(vmOf(cleared).kinds.every((k) => k.cancel === null && !k.held && !k.active));
  assert.ok(flatten(renderPlanSection(cfg(), cleared as never, NOW_MS, renderPlanControls(() => undefined))).includes("Plan helper entities not found"));
  // a running override is judged by its date-and-time record, as before
  const run = old(running(configured(), "hold_battery", 30, 100));
  assert.equal(recOf(run, "hold_battery").read, "active");
  assert.equal(helpersOf(run).active[0]?.expiresText, "2026-11-16 21:40", "the helper's own local text, as before");
  assert.equal(helpersOf(run).active[0]?.note, "");
  assert.ok(kindVm(run, "hold_battery").cancel);
  // an unreadable date-and-time record is still not "cleared"
  const bad = old(configured({ [A_ID("skip_tonight")]: { state: "unavailable" } }));
  assert.equal(recOf(bad, "skip_tonight").read, "unreadable");
  assert.ok(kindVm(bad, "skip_tonight").cancel);
  // one missing absolute record only: that kind is judged by the date-and-time record, the others by both
  const one = configured();
  setEpoch(one, "skip_tonight", undefined);
  setEpoch(one, "hold_battery", NOW_MS + 100 * MIN);
  assert.equal(recOf(one, "hold_battery").read, "active");
  assert.equal(recOf(one, "skip_tonight").read, "cleared");
  assert.match(helpersOf(one).problems.join(" | "), /absolute expiry record of Skip tonight is not installed/);
});

// ---- 5. the read rule is the backend's (a reference model of the template, swept) -------------------------------------------------------------------

type Source = { state: string; attributes?: Record<string, unknown> } | undefined;
/** The backend's rule, restated from the package's template (seconds): source 1 valid when its state is not unknown, unavailable or empty and the attribute is a number; source 2 when a number in 0..4102444800. */
function backendRead(a: number | null, b: number | null, nowSec: number): "active" | "cleared" | "unreadable" {
  const have = [a, b].filter((x): x is number => x !== null);
  const ex = (a !== null && b !== null) || (a !== null && a > nowSec) || (b !== null && b > nowSec) ? Math.max(...have) : null;
  return ex === null ? "unreadable" : ex > nowSec ? "active" : "cleared";
}

test("the card's verdict for every kind equals the backend's rule over a grid of date-and-time records, absolute records and moments", () => {
  const nowSec = NOW_MS / 1000;
  const aCases: [string, Source, number | null][] = [
    ["past", stamp(NOW_MS - 90 * MIN), nowSec - 5400], ["now", stamp(NOW_MS), nowSec], ["future", stamp(NOW_MS + 90 * MIN), nowSec + 5400], ["never", NEVER, 0],
    ["unavailable", { state: "unavailable" }, null], ["unknown", { state: "unknown" }, null], ["empty", { state: "" }, null],
    ["no timestamp", { state: "2026-11-16 20:00:00" }, null], ["timestamp nan", { state: "2026-11-16 20:00:00", attributes: { timestamp: NaN } }, null],
    ["timestamp text", { state: "2026-11-16 20:00:00", attributes: { timestamp: "x" } }, null], ["missing", undefined, null],
  ];
  const bCases: [string, Source, number | null][] = [
    ["past", { state: String(nowSec - 5400) }, nowSec - 5400], ["now", { state: String(nowSec) }, nowSec], ["future", { state: String(nowSec + 5400) }, nowSec + 5400],
    ["zero", { state: "0" }, 0], ["max", { state: "4102444800" }, 4102444800], ["beyond", { state: "4102444801" }, null], ["negative", { state: "-1" }, null],
    ["unavailable", { state: "unavailable" }, null], ["unknown", { state: "unknown" }, null], ["empty", { state: "" }, null], ["text", { state: "soon" }, null],
    ["nan", { state: "nan" }, null], ["inf", { state: "inf" }, null], ["exponent", { state: "1e3" }, 1000],
  ];
  let n = 0;
  for (const kind of KIND_NAMES) {
    for (const [an, a, av] of aCases) {
      for (const [bn, b, bv] of bCases) {
        const s = configured();
        running(s, kind, 600, 0, RESERVE(kind));
        const r = s as Record<string, unknown>;
        if (a === undefined) delete r[A_ID(kind)];
        else r[A_ID(kind)] = a;
        r[EPOCH_ID(kind)] = b;
        const want = backendRead(av, bv, nowSec);
        const got = recOf(s, kind);
        assert.equal(got.read, want, kind + " date-and-time " + an + " / absolute " + bn);
        if (want === "active") assert.equal(got.endMin, Math.round(Math.max(...[av, bv].filter((x): x is number => x !== null)) / 60), "the later instant");
        else if (want === "cleared") assert.ok(got.endMin !== null && got.endMin <= NOW_MIN);
        else assert.equal(got.endMin, null);
        n++;
      }
    }
  }
  assert.equal(n, 3 * 11 * 14);
});

test("the card is never more lenient than the backend: a date-and-time record the card cannot place is unreadable here, never cleared", () => {
  // The backend accepts any date-and-time state text and an infinite timestamp; the card needs a date and time text and a finite timestamp. Stricter means
  // 'unreadable' (held, with a Cancel), never 'cleared' and never 'active' on a guess.
  for (const [what, a] of [["infinite", { state: "2026-11-16 20:00:00", attributes: { timestamp: Infinity } }], ["text state", { state: "soon", attributes: { timestamp: NOW_MS / 1000 + 60 } }]] as const) {
    const s = configured();
    (s as Record<string, unknown>)[A_ID("hold_battery")] = a;
    assert.equal(recOf(s, "hold_battery").read, "unreadable", what);
  }
});

test("the UTC text of an instant that only the absolute record gives is exact (leap day, year end, the year 2100)", () => {
  for (const ms of [Date.UTC(2028, 1, 29, 23, 59), Date.UTC(2027, 11, 31, 23, 59), Date.UTC(2100, 0, 1, 0, 0), Date.UTC(2026, 10, 16, 20, 1), Date.UTC(2027, 2, 28, 1, 0), Date.UTC(2099, 11, 31, 23, 58)]) {
    const s = withEpochText("hold_battery", String(ms / 1000));
    assert.equal(recOf(s, "hold_battery").endText, utc(ms), new Date(ms).toISOString());
  }
});

// ---- 6. the cancel is the existing guarded call and nothing else ---------------------------------------------------------------------------------------

type Calls = unknown[][];
function mount(states: States): { card: Record<string, unknown> & { _renderPlan(): unknown }; calls: Calls } {
  const calls: Calls = [];
  const card = new Card() as unknown as Record<string, unknown> & { _renderPlan(): unknown; setConfig(c: unknown): void; hass?: unknown };
  card.setConfig(planConfig());
  card.hass = { states, callService: (...a: unknown[]) => { calls.push(a); return Promise.resolve(); } };
  return { card, calls };
}
const withNow = <T,>(fn: () => T): T => {
  const real = Date.now;
  Date.now = () => NOW_MS;
  try {
    return fn();
  } finally {
    Date.now = real;
  }
};
const cancelHandlers = (card: { _renderPlan(): unknown }) => handlersOf(card._renderPlan());
const BTN = "data-cancel aria-label"; // the Cancel button's own attribute (the readback's attribute must never be mistaken for it)

test("a Cancel for a record held only by the absolute record, or unreadable, sends exactly the existing guarded call: one script.turn_on with the stored revision", () => {
  const cases: [string, States, KindName][] = [
    ["epoch only", epochOnly("hold_battery", 100), "hold_battery"],
    ["epoch only, power cut", epochOnly("prepare_power_cut", 100), "prepare_power_cut"],
    ["unreadable", withEpochText("skip_tonight", "unavailable"), "skip_tonight"],
  ];
  for (const [what, states, kind] of cases) {
    const { card, calls } = mount(states);
    withNow(() => {
      const before = cancelHandlers(card).length;
      for (const h of cancelHandlers(card)) h.fn();
      assert.ok(before > 0);
    });
    const cancels = calls.filter((c) => (c[2] as { entity_id: string }).entity_id === PLAN_CONTROL_IDS.cancel_script);
    assert.equal(cancels.length, 1, what + ": exactly one cancel among the calls");
    assert.deepEqual(cancels[0], ["script", "turn_on", { entity_id: PLAN_CONTROL_IDS.cancel_script, variables: { kind, expected_revision: 12 } }], what);
    assert.ok(calls.every((c) => isPlanServiceCall({ domain: c[0], service: c[1], data: c[2] }, null)), what + ": every call is on the allow-list");
    const json = JSON.stringify(calls);
    assert.ok(!/input_number|input_datetime|set_value|set_datetime|button\.|switch\.|number\./.test(json.replace(/input_text/g, "")), what + ": no helper, charge, button or inverter entity is named in any call");
  }
});

test("without a readable stored revision the cancel carries none (the script then answers REVISION_UNREADABLE itself); the call is still the same guarded one", () => {
  const s = epochOnly("hold_battery", 100);
  (s as Record<string, unknown>)[Helpers.HELPER_IDS.revision] = { state: "unavailable" };
  assert.deepEqual(kindVm(s, "hold_battery").cancel, cancelOverrideCall("hold_battery", null));
  assert.deepEqual(cancelOverrideCall("hold_battery", null).data, { entity_id: PLAN_CONTROL_IDS.cancel_script, variables: { kind: "hold_battery" } });
});

test("the Start controls are unchanged for a kind the absolute record holds: the same choices and calls as for a date-and-time-led override", () => {
  for (const kind of KIND_NAMES) {
    const viaEpoch = kindVm(epochOnly(kind, 100), kind);
    const viaDate = kindVm(running(configured(), kind, 30, 100, RESERVE(kind)), kind);
    assert.ok(viaEpoch.choices.length > 0);
    assert.deepEqual(viaEpoch.choices, viaDate.choices, kind);
    assert.equal(viaEpoch.blockedReason, viaDate.blockedReason);
    const held = kindVm(withEpochText(kind, "unavailable"), kind);
    assert.deepEqual(held.choices, kindVm(configured(), kind).choices, kind + ": a held kind offers the same starts as an idle one");
    for (const c of viaEpoch.choices) assert.ok(isPlanServiceCall(c.call, null));
  }
  const text = flatten(renderPlanSection(cfg(), epochOnly("hold_battery", 100) as never, NOW_MS, renderPlanControls(() => undefined)));
  assert.ok(text.includes("Start again for"), "the start chips say again, as for any running override");
});

test("with show_plan off, or no plan helper configured, the section is exactly what it was", () => {
  const states = planStates();
  const renderer = renderPlanControls(() => undefined);
  assert.equal(flatten(renderPlanSection(cfg(), states as never, NOW_MS, renderer)), flatten(renderPlanSection(cfg(), states as never, NOW_MS)));
  const off = { ...(planConfig() as Record<string, unknown>), show_plan: false };
  assert.equal(flatten(renderPlanSection(off as never, epochOnly("hold_battery", 100) as never, NOW_MS, renderer)), "");
  // an absolute record alone (nothing else of the package) configures the helpers, half-built, and shows nothing as running
  const lonely = planStates();
  setEpoch(lonely, "hold_battery", NOW_MS + 100 * MIN);
  const h = helpersOf(lonely);
  assert.equal(h.policy.ok, false);
  assert.equal(h.missing.length, Object.keys(Helpers.HELPER_IDS).length - 1);
  assert.match(flatten(renderPlanSection(cfg(), lonely as never, NOW_MS)), /Plan helper entities not found/);
});

// ---- 7. the readback: confirmed, pending, NOT confirmed -------------------------------------------------------------------------------------------------

const ANSWER_BEFORE = "STARTED hold_battery until 2026-11-16 21:40.";
/** The states a cancel leaves behind: both records at the cancel instant (this minute), the revision one higher, the script's answer. */
function afterCancel(kind: KindName, patch: { dateTime?: unknown; epoch?: number | string; revision?: string; answer?: string } = {}): States {
  const s = configured({ [PLAN_CONTROL_IDS.last_result]: { state: patch.answer ?? "CANCELLED " + kind + "." } });
  running(s, kind, 30, 0, RESERVE(kind));
  (s as Record<string, unknown>)[A_ID(kind)] = patch.dateTime ?? stamp(NOW_MS);
  setEpoch(s, kind, patch.epoch ?? NOW_MS);
  (s as Record<string, unknown>)[Helpers.HELPER_IDS.revision] = { state: patch.revision ?? "13" };
  return s;
}
const clicked = (kind: KindName, revision: number | null = 12, answer: string | null = ANSWER_BEFORE): Model.CancelLedger => {
  const ledger: Model.CancelLedger = {};
  Model.noteCall(ledger, cancelOverrideCall(kind, revision), answer);
  return ledger;
};

test("readback: pending until Home Assistant has answered; nothing is assumed from the click", () => {
  for (const kind of KIND_NAMES) {
    const states = configured({ [PLAN_CONTROL_IDS.last_result]: { state: ANSWER_BEFORE } });
    running(states, kind, 30, 100, RESERVE(kind));
    const rb = kindVm(states, kind, clicked(kind)).readback;
    assert.ok(rb, kind);
    assert.equal(rb.outcome, "pending");
    assert.equal(rb.text, "Cancel sent for " + LABEL[kind] + ". Waiting for Home Assistant to answer: the plan revision and both records are read back before it is called cancelled.");
    // the kind is still shown as running, with its Cancel, while it is pending
    assert.ok(kindVm(states, kind, clicked(kind)).cancel);
  }
  assert.equal(kindVm(configured(), "hold_battery", {}).readback, null, "no click, no readback");
});

test("readback: confirmed only when the revision moved and BOTH records read as ended", () => {
  for (const kind of KIND_NAMES) {
    const rb = kindVm(afterCancel(kind), kind, clicked(kind)).readback;
    assert.ok(rb, kind);
    assert.equal(rb.outcome, "confirmed");
    assert.equal(rb.text, "Cancel confirmed for " + LABEL[kind] + ": both records read as ended (plan revision 13).");
    assert.equal(kindVm(afterCancel(kind), kind, clicked(kind)).cancel, null, "and the kind no longer offers a Cancel");
  }
});

test("readback: NOT confirmed while a record still holds (in the future) or cannot be read, even when the script answered CANCELLED", () => {
  for (const kind of KIND_NAMES) {
    const holdsEpoch = kindVm(afterCancel(kind, { epoch: NOW_MS + 60 * MIN }), kind, clicked(kind)).readback;
    assert.ok(holdsEpoch);
    assert.equal(holdsEpoch.outcome, "not_confirmed");
    assert.equal(holdsEpoch.text, "Cancel NOT confirmed for " + LABEL[kind] + ": a record still holds it until " + utc(NOW_MS + 60 * MIN) + ". Home Assistant keeps the hold, and any raised reserve, until a cancel is confirmed.");
    const holdsDate = kindVm(afterCancel(kind, { dateTime: stamp(NOW_MS + 60 * MIN) }), kind, clicked(kind)).readback;
    assert.equal(holdsDate?.outcome, "not_confirmed");
    assert.match(holdsDate?.text ?? "", /a record still holds it until 2026-11-16 21:00\./);
    const unreadable = kindVm(afterCancel(kind, { epoch: "unavailable" }), kind, clicked(kind)).readback;
    assert.equal(unreadable?.outcome, "not_confirmed");
    assert.equal(unreadable?.text, "Cancel NOT confirmed for " + LABEL[kind] + ": a record cannot be read here. Home Assistant keeps the hold, and any raised reserve, until a cancel is confirmed.");
    const dateUnreadable = kindVm(afterCancel(kind, { dateTime: { state: "unavailable" } }), kind, clicked(kind)).readback;
    assert.equal(dateUnreadable?.outcome, "not_confirmed", kind);
  }
});

test("readback: a refusal leaves the revision where it was and is NOT confirmed, with the script's own answer; a refusal about a kind that already ended is confirmed", () => {
  const refused = "REFUSED REVISION_CONFLICT - The plan changed since you looked at it (revision 13); look again and retry.";
  const states = configured({ [PLAN_CONTROL_IDS.last_result]: { state: refused } });
  running(states, "hold_battery", 30, 100);
  const rb = kindVm(states, "hold_battery", clicked("hold_battery")).readback;
  assert.equal(rb?.outcome, "not_confirmed");
  assert.equal(rb?.text, "Cancel NOT confirmed for Hold battery: Home Assistant did not carry it out. Its answer was: " + refused + " A record still holds it until 2026-11-16 21:40. Home Assistant keeps the hold, and any raised reserve, until a cancel is confirmed.");
  const notActive = configured({ [PLAN_CONTROL_IDS.last_result]: { state: "REFUSED NOT_ACTIVE - That override is not active; nothing to cancel." } });
  const rb2 = kindVm(notActive, "hold_battery", clicked("hold_battery")).readback;
  assert.equal(rb2?.outcome, "confirmed");
  assert.equal(rb2?.text, "Nothing to cancel for Hold battery: both records already read as ended.");
});

test("readback: another writer (the revision moved by more than the cancel's one step, or an answer that is not a cancel's) is not claimed as this cancel", () => {
  const s = afterCancel("hold_battery", { revision: "14" });
  assert.equal(kindVm(s, "hold_battery", clicked("hold_battery")).readback, null, "two steps: someone else wrote too");
  const started = afterCancel("hold_battery", { revision: "13", answer: "STARTED skip_tonight until 2026-11-17 07:00." });
  assert.equal(kindVm(started, "hold_battery", clicked("hold_battery")).readback, null, "the answer is a start's");
  const startRefusal = afterCancel("hold_battery", { revision: "12", answer: "REFUSED POLICY_UNCONFIRMED - nope" });
  assert.equal(kindVm(startRefusal, "hold_battery", clicked("hold_battery")).readback, null, "a start's refusal code is not a cancel's");
  const other = kindVm(afterCancel("hold_battery"), "skip_tonight", clicked("hold_battery")).readback;
  assert.equal(other, null, "a cancel of another kind is not shown on this one");
  const otherAnswer = afterCancel("hold_battery", { answer: "CANCELLED skip_tonight." });
  assert.equal(kindVm(otherAnswer, "hold_battery", clicked("hold_battery")).readback, null, "the script cancelled another kind");
});

test("the click memory: a cancel is noted with the revision and answer the card saw, any start of that kind forgets it, nothing else is noted", () => {
  const ledger: Model.CancelLedger = {};
  Model.noteCall(ledger, cancelOverrideCall("hold_battery", 12), "A");
  Model.noteCall(ledger, cancelOverrideCall("skip_tonight", null), null);
  assert.deepEqual(ledger, { hold_battery: { revision: 12, answer: "A" }, skip_tonight: { revision: null, answer: null } });
  Model.noteCall(ledger, startOverrideCall("hold_battery", { expiryMin: 60 }, 12), "B");
  assert.deepEqual(ledger, { skip_tonight: { revision: null, answer: null } }, "a start of Hold battery forgets its cancel");
  Model.noteCall(ledger, { domain: "script", service: "turn_on", data: { entity_id: "script.ecco_dump_to_grid_start_guarded" } }, "C");
  Model.noteCall(ledger, { domain: "script", service: "turn_on", data: { entity_id: PLAN_CONTROL_IDS.cancel_script, variables: { kind: "nonsense" } } }, "D");
  assert.deepEqual(ledger, { skip_tonight: { revision: null, answer: null } });
});

test("the readback never says confirmed while any record is in the future or unreadable (swept over both records, the revision and the answers)", () => {
  const nowSec = NOW_MS / 1000;
  const aCases: [Source, number | null][] = [[stamp(NOW_MS), nowSec], [stamp(NOW_MS + 60 * MIN), nowSec + 3600], [NEVER, 0], [{ state: "unavailable" }, null], [undefined, null]];
  const bCases: [string | undefined, number | null][] = [[String(nowSec), nowSec], [String(nowSec + 3600), nowSec + 3600], ["0", 0], ["unavailable", null], ["junk", null], [undefined, -1]];
  const answers = ["CANCELLED hold_battery.", "REFUSED NOT_ACTIVE - x", "REFUSED REVISION_CONFLICT - x", "REFUSED REVISION_UNREADABLE - x", ANSWER_BEFORE, "", "garbage"];
  let confirmed = 0;
  for (const [a, av] of aCases) {
    for (const [b, bv] of bCases) {
      for (const revision of ["12", "13", "14", "unavailable"]) {
        for (const answer of answers) {
          const s = configured({ [PLAN_CONTROL_IDS.last_result]: { state: answer } });
          running(s, "hold_battery", 30, 0);
          const r = s as Record<string, unknown>;
          if (a === undefined) delete r[A_ID("hold_battery")];
          else r[A_ID("hold_battery")] = a;
          if (b === undefined) delete r[EPOCH_ID("hold_battery")];
          else r[EPOCH_ID("hold_battery")] = { state: b };
          r[Helpers.HELPER_IDS.revision] = { state: revision };
          const rb = kindVm(s, "hold_battery", clicked("hold_battery")).readback;
          if (rb?.outcome === "confirmed") {
            confirmed++;
            const ended = (av === null ? false : av <= nowSec) && (bv === null ? false : bv <= nowSec);
            const epochMissing = b === undefined && av !== null && av <= nowSec;   // an older package: the date-and-time record alone
            assert.ok(ended || epochMissing, "confirmed with a record in the future or unreadable: " + JSON.stringify([a, b, revision, answer]));
          }
        }
      }
    }
  }
  assert.ok(confirmed > 0, "the sweep does reach confirmed");
});

// ---- 8. the card end to end (real card, real bundle of the sources) ------------------------------------------------------------------------------------

/** The checks the epoch Cancel must keep passing, run against a card class (the real one, or one bundled from a source mutant). Returns the problems found. */
export function epochProblems(Ctor: CardCtor): string[] {
  const bad: string[] = [];
  const mk = (states: States) => {
    const calls: unknown[][] = [];
    const card = new Ctor() as unknown as { _renderPlan(): unknown; setConfig(c: unknown): void; hass?: unknown };
    card.setConfig(planConfig());
    card.hass = { states, callService: (...a: unknown[]) => { calls.push(a); return Promise.resolve(); } };
    return {
      card, calls, text: () => flatten(card._renderPlan()),
      press: () => { for (const h of handlersOf(card._renderPlan())) h.fn(); },
      first: () => { handlersOf(card._renderPlan())[0]?.fn(); },   // the first control of the section: a start chip of Hold battery
    };
  };
  const seg = (text: string, kind: string) => text.split("data-control=" + kind)[1]?.split("data-control=")[0] ?? "";
  const cancelsOf = (calls: unknown[][]) => calls.filter((c) => (c[2] as { entity_id: string }).entity_id === PLAN_CONTROL_IDS.cancel_script).map((c) => (c[2] as { variables: { kind: string; expected_revision?: number } }).variables);
  const real = Date.now;
  Date.now = () => NOW_MS;
  try {
    for (const kind of KIND_NAMES) {
      // 1. the absolute record alone holds the kind: a Cancel, with the revision, for that kind only
      {
        const m = mk(epochOnly(kind, 100));
        const t = seg(m.text(), kind);
        if (!t.includes(BTN) || !t.includes("data-control-active")) bad.push(kind + ": a kind held only by the absolute record has no running row or no Cancel");
        if (!t.includes("ends in 1 h 40 min")) bad.push(kind + ": the countdown of the absolute record is not shown");
        if (!t.includes("absolute epoch record")) bad.push(kind + ": the note that only the absolute record holds the kind is not shown");
        m.press();
        const c = cancelsOf(m.calls);
        if (c.length !== 1 || c[0]?.kind !== kind || c[0]?.expected_revision !== 12) bad.push(kind + ": the cancel is not exactly this kind with revision 12: " + JSON.stringify(c));
      }
      // 1b. the date-and-time record cannot be read: the absolute record alone still places and cancels the kind
      {
        const t = seg(mk(epochOnly(kind, 100, { state: "unavailable" })).text(), kind);
        if (!t.includes(BTN) || !t.includes("ends in 1 h 40 min")) bad.push(kind + ": with the date-and-time record unreadable the absolute record does not hold the kind");
      }
      // 1c. an instant inside the minute (not on a minute boundary) is never read earlier than it is: 20 s ahead still holds
      {
        const t = seg(mk(withEpochText(kind, String(NOW_MS / 1000 + 20))).text(), kind);
        if (!t.includes(BTN)) bad.push(kind + ": a record 20 s ahead of now reads as ended");
      }
      // 1d. both records end this very minute: that is ended, not running
      {
        const s = configured();
        (s as Record<string, unknown>)[A_ID(kind)] = stamp(NOW_MS);
        setEpoch(s, kind, NOW_MS);
        if (seg(mk(s).text(), kind).includes(BTN)) bad.push(kind + ": a record that ends this minute still reads as running");
      }
      // 2. the later source wins
      {
        const s = running(configured(), kind, 30, 20, RESERVE(kind));
        setEpoch(s, kind, NOW_MS + 100 * MIN);
        if (!seg(mk(s).text(), kind).includes("ends in 1 h 40 min")) bad.push(kind + ": the earlier date-and-time record shortened the countdown");
        const s2 = running(configured(), kind, 30, 100, RESERVE(kind));
        setEpoch(s2, kind, NOW_MS + 20 * MIN);
        if (!seg(mk(s2).text(), kind).includes("ends in 1 h 40 min")) bad.push(kind + ": the earlier absolute record shortened the countdown");
        const s3 = running(configured(), kind, 30, 100, RESERVE(kind));
        setEpoch(s3, kind, "unavailable");
        const t3 = seg(mk(s3).text(), kind);
        if (!t3.includes(BTN) || !t3.includes("ends in 1 h 40 min") || t3.includes("a record cannot be read here")) bad.push(kind + ": an unreadable absolute record changed what the date-and-time record still shows as running");
      }
      // 3. an unreadable record is held, not cleared, with a Cancel
      {
        const m = mk(withEpochText(kind, "unavailable"));
        const t = seg(m.text(), kind);
        if (!t.includes(BTN) || !t.includes("Held by Home Assistant")) bad.push(kind + ": an unreadable record looks cleared or has no Cancel");
        if (!t.includes("a record cannot be read here") || !t.includes("data-control-note")) bad.push(kind + ": an unreadable record is not explained in plain words");
        if (!m.text().includes("Home Assistant also holds, or cannot read the record of: " + LABEL[kind])) bad.push(kind + ": the headline says none while Home Assistant holds the kind");
        if (!m.text().includes("data-override-held=" + kind)) bad.push(kind + ": the status block does not list the held kind");
        m.press();
        if (cancelsOf(m.calls).length !== 1) bad.push(kind + ": an unreadable record does not send exactly one cancel");
        for (const junk of ["-5", "4102444801"]) {
          const tj = seg(mk(withEpochText(kind, junk)).text(), kind);
          if (!tj.includes(BTN) || !tj.includes("a record cannot be read here")) bad.push(kind + ": an absolute record of " + junk + " is not treated as unreadable");
        }
      }
      // 4. readable and ended: nothing
      {
        const m = mk(configured());
        if (seg(m.text(), kind).includes(BTN) || m.text().includes("Held by Home Assistant")) bad.push(kind + ": a cleared kind shows a Cancel or a held row");
        m.press();
        if (cancelsOf(m.calls).length !== 0) bad.push(kind + ": a cancel is sent for a cleared kind");
      }
      // 5. an older package: the cleared kind never looks active
      {
        const s = configured();
        for (const k of KIND_NAMES) setEpoch(s, k, undefined);
        const m = mk(s);
        if (seg(m.text(), kind).includes(BTN) || m.text().includes("Held by Home Assistant")) bad.push(kind + ": without the absolute record a cleared kind looks active or held");
        const run = running(s, kind, 30, 100, RESERVE(kind));
        if (!seg(mk(run).text(), kind).includes(BTN)) bad.push(kind + ": without the absolute record a running override has no Cancel");
      }
    }
    // 6. the readback, over the real card: pending, then confirmed, then NOT confirmed
    {
      const states = epochOnly("hold_battery", 100);
      (states as Record<string, unknown>)[PLAN_CONTROL_IDS.last_result] = { state: ANSWER_BEFORE };
      const m = mk(states);
      m.press(); // the Cancel of Hold battery (and the starts); the module's click memory notes the cancel
      const t0 = seg(m.text(), "hold_battery");
      if (!t0.includes("data-readback=pending")) bad.push("no pending readback after the Cancel was pressed: " + t0.slice(0, 80));
      Object.assign(states, afterCancel("hold_battery"));
      const t1 = seg(m.text(), "hold_battery");
      if (!t1.includes("data-readback=confirmed") || !t1.includes("both records read as ended")) bad.push("no confirmed readback once both records ended");
      Object.assign(states, afterCancel("hold_battery", { epoch: NOW_MS + 60 * MIN }));
      const t2 = seg(m.text(), "hold_battery");
      if (!t2.includes("data-readback=not_confirmed") || t2.includes("data-readback=confirmed")) bad.push("a record still in the future was not reported as NOT confirmed");
      Object.assign(states, afterCancel("hold_battery", { epoch: "unavailable" }));
      const t3 = seg(m.text(), "hold_battery");
      if (!t3.includes("data-readback=not_confirmed") || !t3.includes("cannot be read here")) bad.push("a record that cannot be read was not reported as NOT confirmed");
      Object.assign(states, afterCancel("hold_battery", { revision: "14" }));
      if (seg(m.text(), "hold_battery").includes("data-readback")) bad.push("a readback is claimed although another writer moved the revision too");
      Object.assign(states, afterCancel("hold_battery", { answer: "STARTED skip_tonight until 2026-11-17 07:00." }));
      if (seg(m.text(), "hold_battery").includes("data-readback")) bad.push("a readback is claimed for an answer that is not a cancel's");
      Object.assign(states, afterCancel("hold_battery"));
      if (!seg(m.text(), "hold_battery").includes("data-readback=confirmed")) bad.push("the confirmed readback does not come back when the same states return");
      m.first(); // a Start of Hold battery: the revision will move for another reason, so the old cancel is forgotten
      if (seg(m.text(), "hold_battery").includes("data-readback")) bad.push("a Start of the kind did not forget the earlier cancel");
    }
  } finally {
    Date.now = real;
  }
  return bad;
}

test("the card end to end: the epoch Cancel, the held row, the readback and the older package pass every check of the real card", async () => {
  const fresh = await loadFreshCard(); // its own module instance, so its click memory starts empty
  assert.deepEqual(epochProblems(fresh), []);
});

// ---- 8b. mutants: each safety-relevant line, lost, is caught by the end-to-end checks above -----------------------------------------------------------

const EPOCH_MUTANTS: { label: string; file: string; find: string; put: string }[] = [
  { label: "the date-and-time record is the only one that can end the later-wins comparison (the absolute record never wins)", file: "plan/helpers.ts", find: "const fromEpoch = b.min > a.min;", put: "const fromEpoch = false;" },
  { label: "the EARLIER of the two valid instants wins (an early restore releases the kind)", file: "plan/helpers.ts", find: "const fromEpoch = b.min > a.min;", put: "const fromEpoch = b.min < a.min;" },
  { label: "an absolute record that is in the future does not hold the kind when the date-and-time record cannot be read", file: "plan/helpers.ts", find: 'if (b.ok && b.min > nowMin) return { read: "active", endMin: b.min, endFrom: "epoch" };', put: "" },
  { label: "a date-and-time record in the future does not hold the kind when the absolute record cannot be read", file: "plan/helpers.ts", find: 'if (a.ok && a.min > nowMin) return { read: "active", endMin: a.min, endFrom: "datetime" };', put: "" },
  { label: "a record that cannot be read is read as cleared", file: "plan/helpers.ts", find: 'return { read: "unreadable", endMin: null, endFrom: null };', put: 'return { read: "cleared", endMin: null, endFrom: null };' },
  { label: "a record that ends this very minute still counts as running", file: "plan/helpers.ts", find: 'read: endMin > nowMin ? "active" : "cleared"', put: 'read: endMin >= nowMin ? "active" : "cleared"' },
  { label: "the absolute record's range is not checked (negative or beyond the year 2100 reads as a time)", file: "plan/helpers.ts", find: "if (v < 0 || v > EPOCH_MAX_SEC) return", put: "if (false) return" },
  { label: "the absolute record is rounded down to the minute (an instant inside the minute reads as ended)", file: "plan/helpers.ts", find: "const min = Math.ceil(v / 60);", put: "const min = Math.floor(v / 60);" },
  { label: "the absolute record is rounded to the nearest minute (up to 30 s early)", file: "plan/helpers.ts", find: "const min = Math.ceil(v / 60);", put: "const min = Math.round(v / 60);" },
  { label: "an older package (no absolute record) is judged unreadable, so a cleared kind looks held", file: "plan/helpers.ts", find: 'if (a.ok && !b.ok && "absent" in b) return { read: a.min > nowMin ? "active" : "cleared", endMin: a.min, endFrom: "datetime" };', put: "" },
  { label: "a missing absolute record is treated as an unreadable one", file: "plan/helpers.ts", find: 'return { ok: false, absent: true, reason: label + " absolute expiry record is not installed." };', put: 'return { ok: false, reason: label + " absolute expiry record is not installed." };' },
  { label: "a kind whose record cannot be read is not listed as held", file: "plan/helpers.ts", find: 'const held = records.filter((r) => r.read !== "cleared" && !active.some((a) => a.override.kind === r.kind));', put: 'const held = records.filter((r) => r.read === "active" && !active.some((a) => a.override.kind === r.kind));' },
  { label: "no Cancel for a kind that is held but not a trusted running row", file: "plan/controlsModel.ts", find: "cancel: row || held ? cancelOverrideCall(kind, revision) : null,", put: "cancel: row ? cancelOverrideCall(kind, revision) : null," },
  { label: "a Cancel is offered for a kind that nothing holds", file: "plan/controlsModel.ts", find: "cancel: row || held ? cancelOverrideCall(kind, revision) : null,", put: "cancel: cancelOverrideCall(kind, revision)," },
  { label: "the readback says confirmed whenever the revision moved, whatever the records say", file: "plan/controlsModel.ts", find: "if (ended && advanced) return {", put: "if (advanced) return {" },
  { label: "the readback treats a record that cannot be read as ended", file: "plan/controlsModel.ts", find: 'const ended = rec.read === "cleared";', put: 'const ended = rec.read !== "active";' },
  { label: "the readback never says pending (the click itself is read as the answer)", file: "plan/controlsModel.ts", find: "if (!advanced && !answered) {", put: "if (false) {" },
  { label: "the readback claims a cancel although another writer moved the revision as well", file: "plan/controlsModel.ts", find: "if (base !== null && revision !== null && revision > base + 1) return null;", put: "" },
  { label: "the readback claims an answer that is not a cancel's", file: "plan/controlsModel.ts", find: "if (answered && !cancelled && !refusal) return null;", put: "" },
  { label: "a Start of the kind does not forget the earlier cancel", file: "plan/controlsModel.ts", find: "else if (call.data.entity_id === PLAN_CONTROL_IDS.start_script) delete ledger[kind];", put: "" },
  { label: "the click is not remembered, so nothing is read back", file: "plan/controls.ts", find: "noteCall(cancelLedger, call, vm.lastResult);", put: "" },
  { label: "the readback is not drawn", file: "plan/controls.ts", find: "${k.readback ? html`", put: "${false ? html`" },
  { label: "the note in plain words is not drawn", file: "plan/controls.ts", find: "${k.note ? html`", put: "${false ? html`" },
  { label: "the headline says none while Home Assistant holds a kind the card cannot show as running", file: "plan/present.ts", find: "return h.held.length > 0 ?", put: "return false ?" },
  { label: "the status block does not list a held kind", file: "plan/view.ts", find: "${b.held.length ? html`", put: "${false ? html`" },
];

test("the epoch Cancel's source mutants: each lost safety-relevant line is caught by the end-to-end checks", async () => {
  assert.ok(EPOCH_MUTANTS.length >= 24);
  const survived: string[] = [];
  for (const m of EPOCH_MUTANTS) {
    const Mut = await loadMutantCard(m.file, m.find, m.put);
    if (epochProblems(Mut).length === 0) survived.push(m.label);
  }
  assert.deepEqual(survived, []);
});

test("an equivalent rewrite of a control label survives (the checks look at behaviour, not at words)", async () => {
  const Eq = await loadMutantCard("plan/controls.ts", ">Cancel</button>", ">Cancel it</button>");
  assert.deepEqual(epochProblems(Eq), []);
});

// ---- 9. static proofs ---------------------------------------------------------------------------------------------------------------------------------------

const root = resolve(import.meta.dirname, "..");
const plain = (f: string): string => readFileSync(join(root, "src", "plan", f), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

test("static: the card's helper ids include the package's three absolute records, and the card names no helper in any call and writes none", () => {
  const ids = Object.values(Helpers.HELPER_IDS) as string[];
  for (const k of KIND_NAMES) assert.ok(ids.includes(EPOCH_ID(k)), EPOCH_ID(k));
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(ids.length, 20);
  for (const f of readdirSync(join(root, "src", "plan"))) {
    const code = plain(f);
    assert.ok(!/set_value|set_datetime|input_number\.set|input_datetime\.set/.test(code), f + " names no helper write service");
    assert.ok(!/\bDate\b/.test(code) || ["clock.ts", "view.ts"].includes(f), f + " reads no clock");
  }
  assert.deepEqual([...new Set([...plain("planActions.ts").matchAll(/service: "([a-z_]+)"/g)].map((m) => m[1]))], ["turn_on"], "the one service the plan section names");
});

void BASE_CONFIG;
