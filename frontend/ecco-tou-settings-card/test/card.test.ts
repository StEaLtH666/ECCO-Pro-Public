// The custom element, driven through a recording DOM shim with a mocked Home Assistant object whose callService records every
// call. The central claims: no UI operation reaches Home Assistant except the three allowed script.turn_on calls, each only
// from the state and with the exact payload the ACS1 scripts expect; nothing reaches the network or a timer.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ACK_PHRASE, H_LOCK, H_RESULT, SCRIPT_ACK, SCRIPT_APPLY, SCRIPT_REVIEW, dongleIds, slotIds } from "../src/model.ts";
import type { StatesLike } from "../src/types.ts";
import { FakeRoot, elementsIn, installDomShim, makeEl } from "./dom-shim.ts";
import { ALL_SLOT_IDS, APPLIED_TEXT, NOW, POWERS, PREFIX, SOCS, SOURCES, applied, baseStates, frontendLike, reviewed, withEntity, withState } from "./fixtures.ts";

const shim = installDomShim();
const mod = await import("../src/ecco-tou-settings-card.ts");
const { EccoTouSettingsCard, CARD_TAG, CARD_VERSION, REFRESH_INTERVAL_MS } = mod;

type Card = InstanceType<typeof EccoTouSettingsCard>;
interface Call {
  domain: string;
  service: string;
  data: unknown;
}

/** A Home Assistant object with a recording callService; its states map refuses writes. */
function hassWith(states: StatesLike, calls: Call[], reject = false): unknown {
  const guarded = new Proxy(states, {
    set(_t, p) {
      throw new TypeError(`write to states ${String(p)}`);
    },
  });
  return {
    states: guarded,
    callService: (domain: string, service: string, data: unknown) => {
      calls.push({ domain, service, data });
      return reject ? Promise.reject(new Error("service refused by the test")) : Promise.resolve(undefined);
    },
  };
}

function newCard(cfg: Record<string, unknown> = {}, now = NOW): { card: Card; root: FakeRoot } {
  const card = new EccoTouSettingsCard();
  card.now = () => now;
  card.setConfig({ type: `custom:${CARD_TAG}`, ...cfg });
  const root = (card as unknown as { shadowRoot: FakeRoot }).shadowRoot;
  return { card, root };
}

function click(root: FakeRoot, attrs: Record<string, string>): void {
  root.dispatch("click", makeEl("button", attrs));
}

function typeInto(root: FakeRoot, action: string, value: string, commit = false): void {
  const el = makeEl("input", { "data-action": action });
  el.value = value;
  root.dispatch("input", el);
  if (commit) root.dispatch("change", el);
}

function enabled(root: FakeRoot, region: string): string[] {
  return [...root.region(region).matchAll(/<button\b([^>]*)>/g)]
    .filter((m) => !/\bdisabled\b/.test(m[1] ?? ""))
    .map((m) => /data-action="([a-z-]+)"/.exec(m[1] ?? "")?.[1] ?? "?");
}

const S3 = slotIds(PREFIX, 3);
const D = dongleIds(PREFIX);

describe("registration and configuration", () => {
  it("defines the element once, announces it once, offers a stub config and a size", () => {
    assert.equal(shim.defined.get(CARD_TAG), EccoTouSettingsCard);
    const cards = (shim.window.customCards ?? []).filter((c) => c.type === CARD_TAG);
    assert.equal(cards.length, 1);
    assert.equal(cards[0]?.name, "ECCO TOU Settings");
    assert.equal(CARD_TAG, "ecco-tou-settings-card");
    assert.equal(CARD_VERSION, "0.1.0");
    assert.deepEqual(EccoTouSettingsCard.getStubConfig(), { entity_prefix: "ecco_clock_dongle" });
    assert.equal(new EccoTouSettingsCard().getCardSize(), 10);
  });

  it("refuses a malformed configuration, including any spacing override", () => {
    const card = new EccoTouSettingsCard();
    assert.throws(() => card.setConfig({ entity_prefix: "Bad Slug" }), /entity_prefix/);
    assert.throws(() => card.setConfig({ apply_spacing_s: 0 }), /unknown option/);
    assert.throws(() => card.setConfig({ allow_writes: true }), /unknown option/);
    assert.throws(() => card.setConfig(null), /mapping/);
  });

  it("renders the six slots, survives garbage hass, keeps one root and one listener per event type", () => {
    const { card, root } = newCard();
    card.hass = hassWith(baseStates(), []);
    assert.equal((root.region("slots").match(/data-action="edit"/g) ?? []).length, 18);
    assert.match(root.region("status"), /Ready to review an edit/);
    for (const bad of [null, undefined, 42, "x", { states: null }, { states: "x" }, []]) {
      assert.doesNotThrow(() => {
        card.hass = bad;
      });
      assert.match(root.region("status"), /Editor unavailable/);
    }
    card.setConfig({ title: "Again" });
    assert.equal((card as unknown as { shadowRoot: FakeRoot }).shadowRoot, root);
    assert.deepEqual([...root.listeners.keys()].sort(), ["change", "click", "input"]);
    assert.equal(root.listeners.get("click")?.length, 1);
    assert.ok(root.innerHTML.includes("Again"));
  });

  it("uses the configured device slug", () => {
    const { card, root } = newCard({ entity_prefix: "site_b" });
    card.hass = hassWith(baseStates("site_b"), []);
    assert.match(root.region("status"), /Ready to review an edit/);
    card.hass = hassWith(baseStates(), []);
    assert.ok(!/Ready to review/.test(root.region("status")), "the default-slug world has no site_b entities");
  });
});

describe("Review: one call, exactly the proposal, only when allowed", () => {
  it("opening an editor row, stepping the value and pressing Review sends one script.turn_on with the exact variables", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(baseStates(), calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    assert.match(root.region("panel"), /Edit slot 3 target SOC/);
    assert.ok(!enabled(root, "panel").includes("review"), "no change yet");
    click(root, { "data-action": "step", "data-delta": "1" });
    assert.match(root.region("panel"), /20 % &rarr; 21 %/);
    typeInto(root, "value", "90", true);
    assert.match(root.region("panel"), /20 % &rarr; 90 %/);
    assert.ok(enabled(root, "panel").includes("review"));
    click(root, { "data-action": "review" });
    assert.deepEqual(calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_REVIEW, variables: { slot: 3, setting: "target_soc", value: 90 } } }]);
    assert.match(root.region("panel"), /Review sent/);
    click(root, { "data-action": "review" });
    assert.equal(calls.length, 1, "no second Review while the first is outstanding");
  });

  it("Review is refused locally for an invalid value, a blocked world, a wrong setting, read-only hass, or no draft", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(baseStates(), calls);
    click(root, { "data-action": "review" });
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "start_time" });
    click(root, { "data-action": "edit", "data-slot": "7", "data-setting": "power" });
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "mode" });
    assert.equal(root.region("panel"), "");
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "power" });
    typeInto(root, "value", "7950", true);
    assert.match(root.region("panel"), /steps of 100/);
    click(root, { "data-action": "review" });
    assert.deepEqual(calls, []);
    typeInto(root, "value", "7900", true);
    // the world changes under the card: Free Power takes the settings before the click
    card.hass = hassWith(withState(baseStates(), D.fpActive, "on"), calls);
    click(root, { "data-action": "review" });
    assert.deepEqual(calls, []);
    assert.match(root.region("status"), /Owned by Free Power/);
    // read-only hass: nothing is enabled, nothing is sent
    card.hass = { states: baseStates() };
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "power" });
    click(root, { "data-action": "review" });
    assert.match(root.region("status"), /Read-only view/);
    assert.equal((root.region("slots").match(/data-action="edit"[^>]*disabled/g) ?? []).length, 18);
  });

  it("a failed call is reported and clears the outstanding request", async () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(baseStates(), calls, true);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "charge_source" });
    click(root, { "data-action": "set-value", "data-value": "Grid" });
    click(root, { "data-action": "review" });
    assert.equal(calls.length, 1);
    assert.deepEqual((calls[0]?.data as { variables: unknown }).variables, { slot: 3, setting: "charge_source", value: "Grid" });
    await Promise.resolve();
    await Promise.resolve();
    assert.match(root.region("panel"), /did not complete: service refused by the test/);
    assert.ok(enabled(root, "panel").includes("review"), "the owner may try again");
  });

  it("an outstanding request expires after 30 s without a result, with a note", () => {
    const calls: Call[] = [];
    let now = NOW;
    const { card, root } = newCard();
    card.now = () => now;
    card.hass = hassWith(baseStates(), calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    typeInto(root, "value", "90", true);
    click(root, { "data-action": "review" });
    now += 31_000;
    card.hass = hassWith(baseStates(), calls);
    assert.match(root.region("panel"), /No result from the editor within 30 s/);
    assert.ok(enabled(root, "panel").includes("review"));
  });
});

describe("Confirm and Apply: the card's own plan, the exact phrase, one call", () => {
  function reviewedWorld(): { card: Card; root: FakeRoot; calls: Call[] } {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(baseStates(), calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    typeInto(root, "value", "90", true);
    click(root, { "data-action": "review" });
    calls.length = 0;
    card.hass = hassWith(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 5), calls);
    return { card, root, calls };
  }

  it("the REVIEWED result opens the confirm panel bound to the live plan; Apply needs the exact phrase", () => {
    const { root, calls } = reviewedWorld();
    assert.match(root.region("panel"), /Confirm and apply/);
    assert.match(root.region("panel"), /SET SLOT 3 TARGET SOC 90 REVIEW 4321/);
    assert.match(root.region("status"), /Plan reviewed; expires in 9:55/);
    click(root, { "data-action": "apply" });
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 432");
    assert.ok(!enabled(root, "panel").includes("apply"));
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, []);
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    assert.ok(enabled(root, "panel").includes("apply"), "the gate flipped on the last character");
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_APPLY, variables: { confirmation: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" } } }]);
    click(root, { "data-action": "apply" });
    assert.equal(calls.length, 1);
  });

  it("a plan that is not this card's proposal (another browser, a reload) cannot be applied here", () => {
    const { card, root, calls } = reviewedWorld();
    // another browser reviews a different value: the live plan changes under the card
    card.hass = hassWith(reviewed(baseStates(), 3, "target_soc", "80", "20", "5555", 2), calls);
    assert.match(root.region("panel"), /not reviewed in this card/);
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 80 REVIEW 5555");
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, []);
    // a fresh card (page reload) sees a live plan but has no draft
    const fresh = newCard();
    fresh.card.hass = hassWith(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 5), calls);
    assert.match(fresh.root.region("panel"), /not reviewed in this card/);
    typeInto(fresh.root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    click(fresh.root, { "data-action": "apply" });
    assert.deepEqual(calls, []);
  });

  it("an expired or used plan, or a blocked world, ends the confirm step without a call", () => {
    const { card, root, calls } = reviewedWorld();
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    card.hass = hassWith(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 601), calls);
    assert.ok(!/Confirm and apply/.test(root.region("panel")));
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, []);
    const again = reviewedWorld();
    typeInto(again.root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    again.card.hass = hassWith(withState(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 5), D.writeEnable, "on"), again.calls);
    assert.match(again.root.region("status"), /A write or recovery arm is on/);
    // S2: the card's own advisory blockers hold Apply (the script would refuse it anyway); the plan stays live for when the arm clears
    assert.ok(!enabled(again.root, "panel").includes("apply"));
    click(again.root, { "data-action": "apply" });
    assert.equal(again.calls.length, 0, "no Apply while a blocker is set");
  });

  it("the provisional spacing rule disables Apply for five minutes after the last outcome", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(applied(baseStates(), 100), calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "power" });
    typeInto(root, "value", "7900", true);
    click(root, { "data-action": "review" });
    calls.length = 0;
    card.hass = hassWith(reviewed(applied(baseStates(), 100), 3, "power", "7900", "8000", "0042", 2), calls);
    typeInto(root, "phrase", "SET SLOT 3 POWER 7900 W REVIEW 0042");
    assert.ok(!enabled(root, "panel").includes("apply"));
    assert.match(root.region("panel"), /Provisional spacing/);
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, []);
    card.hass = hassWith(reviewed(applied(baseStates(), 400), 3, "power", "7900", "8000", "0042", 2), calls);
    assert.ok(enabled(root, "panel").includes("apply"));
    click(root, { "data-action": "apply" });
    assert.equal(calls.length, 1);
    assert.deepEqual((calls[0]?.data as { variables: unknown }).variables, { confirmation: "SET SLOT 3 POWER 7900 W REVIEW 0042" });
  });
});

describe("BUSY, outcomes, Undo and the lock", () => {
  it("BUSY shows the derived progress and no control; success is claimed only on APPLIED AND VERIFIED", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    let s = withState(withState(withState(baseStates(), SCRIPT_APPLY, "on"), "input_boolean.ecco_cfg_edit_in_flight", "on"), H_RESULT, "IN PROGRESS - slot 3 target SOC 20 % -> 90 %: waiting for a fresh configuration read");
    card.hass = hassWith(s, calls);
    assert.match(root.region("panel"), /Applying/);
    assert.equal(enabled(root, "panel").length, 0);
    assert.equal((root.region("slots").match(/data-action="edit"[^>]*disabled/g) ?? []).length, 18);
    s = withState(s, D.manualLastResult, "VERIFIED OK - manual Slot 3 (6 registers)");
    card.hass = hassWith(s, calls);
    assert.match(root.region("panel"), /Firmware readback VERIFIED OK/);
    assert.ok(!/Applied and verified/.test(root.region("panel")), "the firmware's readback alone is not success");
    for (const a of ["apply", "review", "undo", "ack", "edit"]) click(root, { "data-action": a, "data-slot": "3", "data-setting": "power" });
    assert.deepEqual(calls, []);
    card.hass = hassWith(applied(baseStates(), 10), calls);
    assert.match(root.region("panel"), /Applied and verified/);
  });

  it("Undo starts a new Review back to the previous value, only when the records and the live slot agree", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(applied(baseStates(), 400), calls);
    assert.ok(enabled(root, "panel").includes("undo"));
    click(root, { "data-action": "undo" });
    assert.deepEqual(calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_REVIEW, variables: { slot: 3, setting: "target_soc", value: 20 } } }]);
    const other = newCard();
    other.card.hass = hassWith(withState(applied(baseStates(), 400), S3.soc, "85", 20_000), calls);
    assert.ok(!enabled(other.root, "panel").includes("undo"));
    assert.match(other.root.region("panel"), /Undo is not offered/);
    click(other.root, { "data-action": "undo" });
    assert.equal(calls.length, 1);
  });

  it("LOCKED: every edit control off; Acknowledge sends one call only with the exact phrase", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(withState(withState(baseStates(), H_LOCK, "on"), H_RESULT, "UNCERTAIN - the edit was interrupted (Home Assistant restart or script reload) before its outcome was judged"), calls);
    assert.match(root.region("status"), /Edits locked/);
    assert.match(root.region("panel"), /interrupted/);
    assert.equal((root.region("slots").match(/data-action="edit"[^>]*disabled/g) ?? []).length, 18);
    click(root, { "data-action": "ack" });
    typeInto(root, "ack-phrase", "I HAVE CHECKED THE TOU SLOTS ");
    click(root, { "data-action": "ack" });
    assert.deepEqual(calls, []);
    typeInto(root, "ack-phrase", ACK_PHRASE);
    assert.ok(enabled(root, "panel").includes("ack"));
    click(root, { "data-action": "ack" });
    assert.deepEqual(calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_ACK, variables: { confirmation: "I HAVE CHECKED THE TOU SLOTS" } } }]);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "power" });
    click(root, { "data-action": "review" });
    assert.equal(calls.length, 1);
  });

  it("an unrecognised result text fails closed: no editor, no enabled button, no call", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(withState(baseStates(), H_RESULT, "APPLIED - slot 3 target SOC 20 % -> 90 %"), calls);
    assert.match(root.region("panel"), /not one this card recognises/);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    assert.ok(!/Edit slot 3/.test(root.region("panel")));
    for (const el of elementsIn(root.region("panel") + root.region("slots"))) root.dispatch("click", el);
    assert.deepEqual(calls, []);
  });

  it("a missing helper makes the editor unavailable and every control inert", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(withEntity(baseStates(), "input_text.ecco_cfg_edit_review", undefined), calls);
    assert.match(root.region("panel"), /input_text\.ecco_cfg_edit_review/);
    for (const el of elementsIn(root.region("panel") + root.region("slots"))) root.dispatch("click", el);
    assert.deepEqual(calls, []);
  });
});

describe("Window B regressions through the element: P1, P2, P2b, P4, P6", () => {
  it("P1: about 25 s after a FAILED Apply, Review is allowed but Apply is held by the 300 s spacing", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    let s = withState(baseStates(), H_RESULT, "FAILED - a safety check changed just before the Apply (no quiet Modbus window was found); nothing written", 30_000);
    s = withState(s, "input_boolean.ecco_cfg_edit_in_flight", "off", 30_000);
    card.hass = hassWith(s, calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    typeInto(root, "value", "90", true);
    click(root, { "data-action": "review" });
    assert.equal(calls.length, 1, "a Review writes nothing and is allowed");
    card.hass = hassWith(reviewed(s, 3, "target_soc", "90", "20", "4321", 5), calls);
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    assert.ok(!enabled(root, "panel").includes("apply"));
    assert.match(root.region("panel"), /Provisional spacing/);
    click(root, { "data-action": "apply" });
    assert.equal(calls.length, 1, "no Apply within 300 s of the failed one");
  });

  it("P2: Free Power active after an APPLIED AND VERIFIED: no Undo button, and a forged Undo click sends nothing", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(withState(applied(baseStates(), 3600), D.fpActive, "on"), calls);
    assert.ok(!enabled(root, "slots").includes("edit"));
    assert.ok(!enabled(root, "panel").includes("undo"));
    assert.match(root.region("panel"), /Undo is not offered/);
    click(root, { "data-action": "undo" });
    assert.deepEqual(calls, []);
  });

  it("P2b: Free Power starts after the Review: Apply is disabled with the blocker as its reason, and a forged click sends nothing", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(baseStates(), calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    typeInto(root, "value", "90", true);
    click(root, { "data-action": "review" });
    calls.length = 0;
    card.hass = hassWith(withState(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 20), D.fpActive, "on"), calls);
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    assert.match(root.region("status"), /Owned by Free Power/);
    assert.ok(!enabled(root, "panel").includes("apply"));
    assert.match(root.region("panel"), /Owned by Free Power[^<]*The editor would refuse this Apply/);
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, []);
    // the owner clears: Apply becomes available again, same plan, same phrase
    card.hass = hassWith(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 25), calls);
    assert.ok(enabled(root, "panel").includes("apply"));
  });

  it("P4: an unrecognised result disables the pens too, and forged edit / review clicks send nothing", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(withState(baseStates(), H_RESULT, "SOMETHING ELSE ENTIRELY", 60_000), calls);
    assert.match(root.region("panel"), /every edit control stays disabled/);
    assert.equal((root.region("slots").match(/data-action="edit"[^>]*disabled/g) ?? []).length, 18);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    typeInto(root, "value", "90", true);
    click(root, { "data-action": "review" });
    assert.deepEqual(calls, []);
  });

  it("P6: frontend-shaped states (no last_reported, values unchanged for 3 h, poll current): pens enabled, labelled honestly; Undo offered after APPLIED AND VERIFIED", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(frontendLike(baseStates(), ALL_SLOT_IDS, 3 * 3_600_000), calls);
    assert.equal((root.region("slots").match(/data-action="edit"[^>]*disabled/g) ?? []).length, 0);
    assert.match(root.region("slots"), /unchanged 3 h; poll current/);
    let s = applied(baseStates(), 400);
    s = frontendLike(s, ALL_SLOT_IDS.filter((id) => id !== S3.soc), 3 * 3_600_000);
    s[S3.soc] = { ...(s[S3.soc] as object), state: "90", attributes: { unit_of_measurement: "%" }, last_changed: new Date(NOW - 400_000).toISOString(), last_updated: new Date(NOW - 400_000).toISOString() };
    card.hass = hassWith(s, calls);
    assert.ok(enabled(root, "panel").includes("undo"));
    click(root, { "data-action": "undo" });
    assert.equal(calls.length, 1);
    assert.deepEqual((calls[0]?.data as { variables: unknown }).variables, { slot: 3, setting: "target_soc", value: 20 });
  });
});

describe("Window B re-check items through the element: P1, P2, P3", () => {
  it("P1: the reviewed slot's raw flags become unavailable after the Review: Apply disabled, forged click sends nothing, back when they return", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    card.hass = hassWith(baseStates(), calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    typeInto(root, "value", "90", true);
    click(root, { "data-action": "review" });
    calls.length = 0;
    const plan = reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 20);
    card.hass = hassWith(withState(plan, S3.flags, "unavailable", 5000), calls);
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    assert.ok(!enabled(root, "panel").includes("apply"));
    assert.match(root.region("panel"), /raw flags are unreadable/);
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, []);
    card.hass = hassWith(plan, calls);
    assert.ok(enabled(root, "panel").includes("apply"));
  });

  it("P2: Acknowledge is held while the Apply is still in flight, and sent once it is judged", () => {
    const calls: Call[] = [];
    const { card, root } = newCard();
    const locked = withState(withState(baseStates(), H_LOCK, "on"), H_RESULT, "UNCERTAIN - firmware: VERIFY FAILED; later read: incomplete");
    card.hass = hassWith(withState(locked, "input_boolean.ecco_cfg_edit_in_flight", "on"), calls);
    typeInto(root, "ack-phrase", ACK_PHRASE);
    assert.ok(!enabled(root, "panel").includes("ack"));
    click(root, { "data-action": "ack" });
    assert.deepEqual(calls, []);
    card.hass = hassWith(locked, calls);
    assert.ok(enabled(root, "panel").includes("ack"));
    click(root, { "data-action": "ack" });
    assert.equal(calls.length, 1);
  });

  it("P3: a click the handler refuses redraws the controls as they now are (a plan that expired by time alone)", () => {
    const calls: Call[] = [];
    let now = NOW;
    const { card, root } = newCard();
    card.now = () => now;
    card.hass = hassWith(baseStates(), calls);
    click(root, { "data-action": "edit", "data-slot": "3", "data-setting": "target_soc" });
    typeInto(root, "value", "90", true);
    click(root, { "data-action": "review" });
    calls.length = 0;
    card.hass = hassWith(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 590), calls);
    typeInto(root, "phrase", "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    assert.ok(enabled(root, "panel").includes("apply"), "ten seconds before expiry");
    now += 20_000;   // time passes with no hass update
    click(root, { "data-action": "apply" });
    assert.deepEqual(calls, [], "expired: not sent");
    assert.match(root.region("panel"), /Review expired or not current/, "the refused click redrew the panel without a hass update");
    assert.ok(!enabled(root, "panel").includes("apply"));
  });
});

describe("H2: every slot and every setting through the element, with every other route trapped", () => {
  it("Review and Apply for all six slots x three settings send exactly one allowed call each; nothing touches the page, the window, the connection or any other hass property", () => {
    const rec = shim.rec;
    rec.calls.length = 0;
    const routes: string[] = [];
    const g = globalThis as unknown as Record<string, unknown>;
    const trap = (obj: object, prop: string): (() => void) => {
      const had = Object.getOwnPropertyDescriptor(obj, prop);
      Object.defineProperty(obj, prop, {
        configurable: true,
        get() {
          routes.push(prop);
          return undefined;
        },
      });
      return () => {
        if (had) Object.defineProperty(obj, prop, had);
        else delete (obj as Record<string, unknown>)[prop];
      };
    };
    const restores = [trap(g, "document"), trap(g, "hass"), trap(shim.window as object, "parent"), trap(shim.window as object, "top"), trap(shim.window as object, "opener")];
    const calls: Call[] = [];
    const reads = new Set<string>();
    const hassOf = (states: StatesLike): unknown =>
      new Proxy(
        {
          states,
          callService: (domain: string, service: string, data: unknown) => {
            calls.push({ domain, service, data });
            return Promise.resolve(undefined);
          },
          connection: { sendMessagePromise: () => routes.push("connection.sendMessagePromise"), socket: { send: () => routes.push("socket.send") } },
          callWS: () => routes.push("callWS"),
          callApi: () => routes.push("callApi"),
        },
        {
          get(t, p, r) {
            reads.add(String(p));
            return Reflect.get(t, p, r);
          },
        },
      );
    try {
      shim.noTimers(() => {
        for (let slot = 1; slot <= 6; slot++) {
          for (const setting of ["target_soc", "power", "charge_source"] as const) {
            const { card, root } = newCard();
            const base = baseStates();
            card.hass = hassOf(base);
            const live = setting === "target_soc" ? SOCS[slot - 1] : setting === "power" ? POWERS[slot - 1] : SOURCES[slot - 1];
            const want = setting === "target_soc" ? (live === "90" ? "80" : "90") : setting === "power" ? (live === "7900" ? "7800" : "7900") : live === "Grid" ? "None" : "Grid";
            calls.length = 0;
            click(root, { "data-action": "edit", "data-slot": String(slot), "data-setting": setting });
            if (setting === "charge_source") click(root, { "data-action": "set-value", "data-value": want });
            else typeInto(root, "value", want, true);
            click(root, { "data-action": "review" });
            assert.deepEqual(calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_REVIEW, variables: { slot, setting, value: setting === "charge_source" ? want : Number(want) } } }], `review slot ${slot} ${setting}`);
            calls.length = 0;
            card.hass = hassOf(reviewed(base, slot, setting, want, live ?? "", "4321", 5));
            const phrase = setting === "target_soc" ? `SET SLOT ${slot} TARGET SOC ${want} REVIEW 4321` : setting === "power" ? `SET SLOT ${slot} POWER ${want} W REVIEW 4321` : `SET SLOT ${slot} CHARGE SOURCE ${want.toUpperCase()} REVIEW 4321`;
            typeInto(root, "phrase", phrase);
            click(root, { "data-action": "apply" });
            assert.deepEqual(calls, [{ domain: "script", service: "turn_on", data: { entity_id: SCRIPT_APPLY, variables: { confirmation: phrase } } }], `apply slot ${slot} ${setting}`);
            // every other rendered control, in this state, too
            for (const el of elementsIn([root.innerHTML, root.region("status"), root.region("slots"), root.region("panel")].join("\n"))) root.dispatch("click", el);
          }
        }
      });
    } finally {
      for (const r of restores) r();
    }
    assert.deepEqual(routes, [], "no page, window, connection, websocket or API route was touched");
    assert.deepEqual(rec.calls, [], "no network, no timer");
    assert.deepEqual([...reads].sort(), ["callService", "states"], "only states and the service function were read from hass");
  });
});

describe("no other authority: drive everything, record everything", () => {
  it("every rendered control in every state, plus forged actions, produces only the allowed calls and no network or timer use", () => {
    const rec = shim.rec;
    rec.calls.length = 0;
    const calls: Call[] = [];
    const worlds: StatesLike[] = [
      baseStates(),
      reviewed(baseStates(), 3, "target_soc", "90", "20"),
      applied(baseStates(), 400),
      withState(baseStates(), H_LOCK, "on"),
      withState(baseStates(), SCRIPT_APPLY, "on"),
      withState(baseStates(), H_RESULT, "zzz"),
      withEntity(baseStates(), SCRIPT_REVIEW, undefined),
    ];
    const { card, root } = newCard();
    shim.noTimers(() => {
      for (const w of worlds) {
        card.hass = hassWith(w, calls);
        for (let pass = 0; pass < 2; pass++) {
          const html = [root.innerHTML, root.region("badges"), root.region("status"), root.region("slots"), root.region("panel")].join("\n");
          for (const el of elementsIn(html)) {
            if (el.tag === "input") {
              for (const v of ["90", "<script>", "SET SLOT 3 TARGET SOC 90 REVIEW 4321", ACK_PHRASE, ""]) {
                el.value = v;
                root.dispatch("input", el);
                root.dispatch("change", el);
              }
            } else {
              root.dispatch("click", el);
            }
          }
        }
        for (const a of ["apply", "ack", "undo", "review", "turn_on", "press", "write", "", "set-value", "step"]) {
          click(root, { "data-action": a, "data-slot": "1", "data-setting": "power", "data-value": "Grid", "data-delta": "100" });
        }
        root.dispatch("click", null);
        root.dispatch("click", {});
        root.dispatch("input", null);
        root.dispatch("change", { value: "x" });
      }
    });
    assert.deepEqual(rec.calls, [], "no network, no timer");
    for (const c of calls) {
      assert.equal(c.domain, "script");
      assert.equal(c.service, "turn_on");
      const d = c.data as { entity_id: string; variables: Record<string, unknown> };
      assert.ok([SCRIPT_REVIEW, SCRIPT_APPLY, SCRIPT_ACK].includes(d.entity_id), d.entity_id);
      assert.deepEqual(Object.keys(d).sort(), ["entity_id", "variables"]);
    }
    assert.ok(calls.length >= 1, "the drive did exercise at least one allowed call");
    assert.ok(calls.every((c) => (c.data as { entity_id: string }).entity_id !== SCRIPT_APPLY || (c.data as { variables: { confirmation: string } }).variables.confirmation === "SET SLOT 3 TARGET SOC 90 REVIEW 4321"));
    assert.ok(!Object.values(card).some((v) => v !== null && typeof v === "object" && "callService" in (v as object)), "the hass object is never stored");
  });

  it("negative control: the shim's recorder catches timers and network", () => {
    const before = shim.rec.calls.length;
    shim.noTimers(() => {
      setTimeout(() => undefined, 1);
      void fetch("http://127.0.0.1:1/").catch(() => undefined);
    });
    assert.deepEqual(shim.rec.calls.slice(before), ["setTimeout", "fetch"]);
    shim.rec.calls.length = before;
  });

  it("result text is escaped all the way to the shadow DOM", () => {
    const { card, root } = newCard();
    card.hass = hassWith(withState(baseStates(), H_RESULT, 'FAILED - <img src=x onerror="alert(1)">; nothing written'), []);
    assert.ok(!root.region("panel").includes("<img"));
    assert.ok(root.region("panel").includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
  });

  it("regions are rewritten only when their content changed; countdowns still age", () => {
    const states = reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 5);
    let now = NOW;
    const { card, root } = newCard();
    card.now = () => now;
    card.hass = hassWith(states, []);
    const slotsWrites = root.writesOf("slots");
    const panelWrites = root.writesOf("panel");
    card.hass = hassWith(states, []);
    assert.equal(root.writesOf("slots"), slotsWrites, "nothing changed: no rewrite");
    typeInto(root, "phrase", "SET SLOT");
    assert.equal(root.writesOf("panel"), panelWrites, "typing does not rewrite the panel (the caret stays)");
    now += REFRESH_INTERVAL_MS + 1000;
    card.hass = hassWith(states, []);
    assert.match(root.region("status"), /expires in 9:39/);
    assert.ok(root.writesOf("slots") > slotsWrites, "freshness ages on the refresh interval");
    assert.match(root.region("panel"), /SET SLOT 3 TARGET SOC 90 REVIEW 4321/);
    assert.ok(APPLIED_TEXT.length > 0);
  });
});
