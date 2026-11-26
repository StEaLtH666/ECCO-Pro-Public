// Rendering tests: escaping, disabled controls with their reasons, the panel per editor state, and the masked (change-key) form.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { context, dongleIds, editorView, londonMinutes, slotIds, slotView } from "../src/model.ts";
import type { Context } from "../src/model.ts";
import { esc, renderBadges, renderPanel, renderShell, renderSlots, renderStatus } from "../src/render.ts";
import type { PanelInput } from "../src/render.ts";
import { STYLES, TOUCH_TARGET_PX } from "../src/styles.ts";
import type { Draft, SlotView, StatesLike } from "../src/types.ts";
import { ALL_SLOT_IDS, APPLIED_TEXT, NOW, PREFIX, applied, baseStates, config, frontendLike, reviewed, wall, withEntity, withState } from "./fixtures.ts";

const CFG = config();
const D = dongleIds(PREFIX);

function input(states: StatesLike, over: Partial<PanelInput> = {}, nowMs = NOW): PanelInput {
  const cfg = over.config ?? CFG;
  const now = new Date(nowMs);
  const ctx: Context = context(states, cfg, nowMs, now);
  const slots: SlotView[] = [];
  for (let n = 1; n <= 6; n++) slots.push(slotView(states, cfg, n, nowMs, londonMinutes(nowMs), ctx));
  const editor = editorView(states, cfg, nowMs, now, ctx, slots);
  return {
    config: cfg, states, editor, slots, ctx, draft: null, typed: "", ackTyped: "", sent: null, canCall: true, startInfo: false,
    lastError: null, nowMs, powerLabel: "Discharge limit", touEnabled: "on", configAgeText: "Values read 20 s ago", ...over,
  };
}

function buttons(html: string): { attrs: string }[] {
  return [...html.matchAll(/<button\b([^>]*)>/g)].map((m) => ({ attrs: m[1] ?? "" }));
}

function enabledActions(html: string): string[] {
  return buttons(html)
    .filter((b) => !/\bdisabled\b/.test(b.attrs))
    .map((b) => /data-action="([a-z-]+)"/.exec(b.attrs)?.[1] ?? "?");
}

describe("escaping and shell", () => {
  it("escapes every special character", () => {
    assert.equal(esc(`<a href="x">'&`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;");
    assert.equal(esc(null), "");
  });

  it("the shell has the four regions and the footer, and every button declares type=button", () => {
    const shell = renderShell("T", STYLES, "foot");
    for (const r of ["badges", "status", "slots", "panel"]) assert.ok(shell.includes(`data-region="${r}"`), r);
    assert.ok(shell.includes("foot"));
    const all = [renderSlots(input(baseStates())), renderPanel(input(reviewed(baseStates(), 3, "target_soc", "90", "20"), { draft: { slot: 3, setting: "target_soc", value: "90" } })),
      renderPanel(input(withState(baseStates(), "input_boolean.ecco_cfg_edit_review_required", "on"))), renderPanel(input(applied(baseStates())))].join("");
    for (const b of buttons(all)) assert.match(b.attrs, /type="button"/);
    assert.ok(STYLES.includes(`min-height:${TOUCH_TARGET_PX}px`));
    assert.equal(TOUCH_TARGET_PX, 44);
  });
});

describe("status line and badges", () => {
  it("says ready, or the first blocker, or read-only", () => {
    assert.match(renderStatus(input(baseStates())), /Ready to review an edit/);
    const locked = renderStatus(input(withState(baseStates(), "input_boolean.ecco_cfg_edit_review_required", "on")));
    assert.match(locked, /Edits locked/);
    assert.match(locked, /class="status lock"/);
    assert.match(renderStatus(input(withState(baseStates(), D.fpActive, "on"))), /Owned by Free Power/);
    assert.match(renderStatus(input(baseStates(), { canCall: false })), /Read-only view/);
    assert.match(renderStatus(input(withState(baseStates(), "input_text.ecco_cfg_edit_last_result", "SOMETHING ELSE ENTIRELY"))), /not one this card recognises/, "N3: the status line names the result problem instead of 'Ready'");
    assert.match(renderStatus(input(applied(baseStates(), 100))), /Next Apply advised in 3:20/);
    assert.match(renderStatus(input(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 30))), /Plan reviewed; expires in 9:30/);
    assert.match(renderBadges(input(baseStates())), /TOU master on/);
    assert.match(renderBadges(input(baseStates())), /Saved profile and shadow: Safety view/);
  });
});

describe("the slot table", () => {
  it("renders six rows, the active slot, the start-time lock and a pen per editable field", () => {
    const html = renderSlots(input(baseStates()));
    assert.equal((html.match(/<li class="slot/g) ?? []).length, 7, "six slots plus the wide-layout header row");
    assert.equal((html.match(/data-action="edit"/g) ?? []).length, 18);
    assert.equal((html.match(/data-action="start-info"/g) ?? []).length, 6);
    assert.ok(html.includes('<span class="badge ok">now</span>'));
    assert.ok(html.includes("00:25 &ndash; 00:30"), "slot 6 wraps to slot 1's start");
    assert.equal((html.match(/live 20 s; poll current/g) ?? []).length, 6);
    assert.ok(!html.includes("not editable here. This site"), "the explanation shows on request only");
    assert.ok(renderSlots(input(baseStates(), { startInfo: true })).includes("wraps midnight"));
    assert.ok(html.includes("Discharge limit"));
    assert.ok(!/<button[^>]*data-action="edit"[^>]*disabled/.test(html), "idle, healthy: every pen enabled");
  });

  it("disables pens with the reason in the title, and all of them when read-only or blocked", () => {
    let html = renderSlots(input(withState(baseStates(), "sensor.ecco_clock_dongle_ecco_timezone3_power", "2550", 20_000)));
    const pen3 = /<button[^>]*data-slot="3" data-setting="power"[^>]*>/.exec(html)?.[0] ?? "";
    assert.match(pen3, /disabled aria-disabled="true" title="[^"]*not a multiple of 100 W/);
    html = renderSlots(input(baseStates(), { canCall: false }));
    assert.equal((html.match(/data-action="edit"[^>]*disabled/g) ?? []).length, 18);
    assert.match(html, /Read-only view/);
    html = renderSlots(input(withState(baseStates(), D.dgActive, "on")));
    assert.equal((html.match(/data-action="edit"[^>]*disabled/g) ?? []).length, 18);
    assert.match(html, /class="slot owned"|class="slot active owned"/);
  });

  it("B1: an unchanged slot under a current poll is labelled 'unchanged ...; poll current' and stays editable; stale when the poll is not current", () => {
    let html = renderSlots(input(frontendLike(baseStates(), ALL_SLOT_IDS, 3 * 3_600_000)));
    assert.equal((html.match(/unchanged 3 h; poll current/g) ?? []).length, 6);
    assert.equal((html.match(/data-action="edit"[^>]*disabled/g) ?? []).length, 0);
    html = renderSlots(input(withState(frontendLike(baseStates(), ALL_SLOT_IDS, 3 * 3_600_000), D.configUpdate, wall(400_000), 400_000)));
    assert.equal((html.match(/stale 3 h; poll not current/g) ?? []).length, 6);
    assert.equal((html.match(/data-action="edit"[^>]*disabled/g) ?? []).length, 18);
  });

  it("N2 / O-5: every freshness label says only what its branch checked: the value's own age, and the poll from its own flag", () => {
    const narrow = config({ max_age_configuration_s: 60 });
    let s = baseStates();
    for (const id of Object.values(slotIds(PREFIX, 3))) s = withState(s, id, (s[id] as { state: string }).state, 200_000);
    let html = renderSlots(input(s, { config: narrow }));
    const row = (h: string): string => h.split('<li class="slot')[4] ?? "";
    assert.match(row(html), /reported 3 min; poll current/);
    assert.ok(!/stale/.test(row(html)));
    assert.ok(!/data-action="edit"[^>]*disabled/.test(row(html)), "editable, and said so");
    // the same row under a stale poll: "reported" stays true, the poll claim flips, and it is not editable
    html = renderSlots(input(withState(s, D.configUpdate, wall(400_000), 400_000), { config: narrow }));
    assert.match(row(html), /reported 3 min; poll not current/);
    assert.ok(/data-action="edit"[^>]*disabled/.test(row(html)));
    // a value with no timestamp: "unverified", with the poll's own state
    s = withEntity(baseStates(), slotIds(PREFIX, 3).mode, { state: "General" });
    assert.match(row(renderSlots(input(s))), /timestamp unverified; poll current/);
    assert.match(row(renderSlots(input(withState(s, D.configUpdate, wall(400_000), 400_000)))), /timestamp unverified; poll not current/);
    // a missing value under a current poll is "value unavailable; poll current", never a poll complaint
    assert.match(row(renderSlots(input(withState(baseStates(), slotIds(PREFIX, 3).soc, "unavailable")))), /value unavailable; poll current/);
    // a wide label window never makes a stale row "live": 400 s old values read "stale", editable only by the poll
    const wide = config({ max_age_configuration_s: 86400 });
    let old = baseStates();
    for (const id of Object.values(slotIds(PREFIX, 3))) old = withState(old, id, (old[id] as { state: string }).state, 400_000);
    assert.match(row(renderSlots(input(old, { config: wide }))), /unchanged 7 min; poll current/);
    assert.ok(!/>live /.test(row(renderSlots(input(old, { config: wide })))));
    assert.match(row(renderSlots(input(withState(old, D.configUpdate, wall(400_000), 400_000), { config: wide }))), /stale 7 min; poll not current/);
  });

  it("escapes entity text", () => {
    const html = renderSlots(input(withState(baseStates(), "sensor.ecco_clock_dongle_ecco_timezone2_charge", '<img src=x onerror="alert(1)">', 20_000)));
    assert.ok(!html.includes("<img"));
    assert.ok(html.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
  });
});

describe("the panel per state", () => {
  it("IDLE without a draft renders nothing; with a draft, the editor whose Review is enabled only for a valid change", () => {
    assert.equal(renderPanel(input(baseStates())), "");
    const d: Draft = { slot: 3, setting: "target_soc", value: "20" };
    let html = renderPanel(input(baseStates(), { draft: d }));
    assert.match(html, /Edit slot 3 target SOC/);
    assert.deepEqual(enabledActions(html), ["step", "step", "cancel"], "no change: Review disabled");
    assert.match(html, /No change/);
    html = renderPanel(input(baseStates(), { draft: { ...d, value: "90" } }));
    assert.deepEqual(enabledActions(html), ["step", "step", "review", "cancel"]);
    assert.match(html, /20 % &rarr; 90 %/);
    assert.match(html, /register 270/);
    assert.match(html, /Rewritten unchanged: start 12:00, end 16:35, power 8000 W, charge source None, mode General/);
    html = renderPanel(input(baseStates(), { draft: { slot: 3, setting: "charge_source", value: "Grid" } }));
    assert.match(html, /data-action="set-value" data-value="Grid" aria-pressed="true"/);
    assert.match(html, /Dump to Grid whose window overlaps it refuse at start/);
    html = renderPanel(input(baseStates(), { draft: { ...d, value: "90" }, sent: { kind: "review", ageSeconds: 3 } }));
    assert.match(html, /Review sent 3 s ago/);
    assert.ok(!enabledActions(html).includes("review"));
    html = renderPanel(input(baseStates(), { draft: { ...d, value: "90" }, canCall: false }));
    assert.ok(!enabledActions(html).includes("review"));
  });

  it("REVIEWED: Apply is enabled only for this card's own plan, the exact phrase and no spacing wait", () => {
    const states = reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 30);
    const mine: Draft = { slot: 3, setting: "target_soc", value: "90" };
    let html = renderPanel(input(states, { draft: mine }));
    assert.match(html, /Confirm and apply/);
    assert.match(html, /SET SLOT 3 TARGET SOC 90 REVIEW 4321/);
    assert.match(html, /expires in about <strong>10 min<\/strong>/);
    assert.deepEqual(enabledActions(html), ["cancel"]);
    html = renderPanel(input(states, { draft: mine, typed: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" }));
    assert.deepEqual(enabledActions(html), ["apply", "cancel"]);
    html = renderPanel(input(states, { draft: mine, typed: "set slot 3 target soc 90 review 4321" }));
    assert.deepEqual(enabledActions(html), ["cancel"]);
    html = renderPanel(input(states, { draft: { slot: 3, setting: "target_soc", value: "80" }, typed: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" }));
    assert.deepEqual(enabledActions(html), ["cancel"]);
    assert.match(html, /not reviewed in this card/);
    assert.ok(!html.includes('data-action="phrase"'), "no phrase box for a plan that is not this card's");
    html = renderPanel(input(states, { draft: null, typed: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" }));
    assert.deepEqual(enabledActions(html), ["cancel"]);
    const spaced = applied(states, 100);
    html = renderPanel(input(reviewed(spaced, 3, "target_soc", "90", "20", "4321", 30), { draft: mine, typed: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" }));
    assert.deepEqual(enabledActions(html), ["cancel"]);
    assert.match(html, /Provisional spacing: wait about 4 min/);
    html = renderPanel(input(states, { draft: mine, typed: "SET SLOT 3 TARGET SOC 90 REVIEW 4321", canCall: false }));
    assert.deepEqual(enabledActions(html), ["cancel"]);
  });

  it("BUSY: the progress strip and no control", () => {
    const states = withState(withState(withState(baseStates(), "script.ecco_cfg_apply_tou_slot_setting", "on"), "input_boolean.ecco_cfg_edit_in_flight", "on"), "input_text.ecco_cfg_edit_last_result", "IN PROGRESS - slot 3 target SOC 20 % -> 90 %: waiting for a fresh configuration read");
    const html = renderPanel(input(states, { draft: { slot: 3, setting: "target_soc", value: "90" } }));
    assert.match(html, /Applying/);
    assert.equal(buttons(html).length, 0);
    assert.equal((html.match(/<li class="seen"/g) ?? []).length, 1);
    assert.match(html, /Success is reported only when the editor itself writes APPLIED AND VERIFIED/);
  });

  it("LOCKED: the verbatim text, the recovery steps and an Acknowledge that needs the exact phrase", () => {
    const states = withState(withState(baseStates(), "input_boolean.ecco_cfg_edit_review_required", "on"), "input_text.ecco_cfg_edit_last_result", "UNCERTAIN - firmware: VERIFY FAILED; later read: incomplete");
    let html = renderPanel(input(states));
    assert.match(html, /manual review needed/);
    assert.match(html, /UNCERTAIN - firmware: VERIFY FAILED/);
    assert.match(html, /Do not retry/);
    assert.deepEqual(enabledActions(html), []);
    html = renderPanel(input(states, { ackTyped: "I HAVE CHECKED THE TOU SLOTS" }));
    assert.deepEqual(enabledActions(html), ["ack"]);
    html = renderPanel(input(states, { ackTyped: "i have checked the tou slots" }));
    assert.deepEqual(enabledActions(html), []);
    // P2: the tail of the Apply (in flight or the script still on) holds Acknowledge even with the exact phrase
    html = renderPanel(input(withState(states, "input_boolean.ecco_cfg_edit_in_flight", "on"), { ackTyped: "I HAVE CHECKED THE TOU SLOTS" }));
    assert.deepEqual(enabledActions(html), []);
    assert.match(html, /still being judged/);
  });

  it("P5: an expired or code-mismatched REVIEWED plan in OUTCOME is titled as expired, not as unrecognised", () => {
    const html = renderPanel(input(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 660)));
    assert.match(html, /Review expired or not current: review again/);
    assert.ok(!/not recognised/.test(html));
  });

  it("P1: Apply is held when the reviewed slot itself becomes ineligible after the Review", () => {
    const states = withState(reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 30), slotIds(PREFIX, 3).flags, "unavailable", 20_000);
    const html = renderPanel(input(states, { draft: { slot: 3, setting: "target_soc", value: "90" }, typed: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" }));
    assert.deepEqual(enabledActions(html), ["cancel"]);
    assert.match(html, /Slot 3: The slot&#39;s raw flags are unreadable/);
  });

  it("OUTCOME: applied with Undo, failed / refused verbatim, uncertain, and unknown fails closed", () => {
    let html = renderPanel(input(applied(baseStates())));
    assert.match(html, /Applied and verified/);
    assert.match(html, /Undo: review slot 3 target SOC back to 20 %/);
    assert.deepEqual(enabledActions(html), ["undo"]);
    assert.match(html, new RegExp(esc(APPLIED_TEXT).slice(0, 40)));
    html = renderPanel(input(withState(applied(baseStates()), "sensor.ecco_clock_dongle_ecco_timezone3_soc", "20", 20_000)));
    assert.match(html, /Undo is not offered/);
    assert.deepEqual(enabledActions(html), []);
    html = renderPanel(input(withState(baseStates(), "input_text.ecco_cfg_edit_last_result", "FAILED - the firmware refused the Apply (REJECTED - bus busy); nothing written (counter and later reads agree)")));
    assert.match(html, /did not complete: nothing written/);
    assert.match(html, /REJECTED - bus busy/);
    html = renderPanel(input(withState(baseStates(), "input_text.ecco_cfg_edit_last_result", "REVIEW REFUSED - supervision not stable or a failback episode is open; nothing written")));
    assert.match(html, /Refused: nothing written/);
    assert.match(html, /supervision not stable or a failback episode is open/);
    assert.match(html, /supervised dongle reboot clears it/, "the shadow-latch explanation rides on the Review's own refusal");
    html = renderPanel(input(withState(baseStates(), "input_text.ecco_cfg_edit_last_result", "some new text the card has never seen"), { draft: { slot: 3, setting: "target_soc", value: "90" } }));
    assert.match(html, /not one this card recognises/);
    assert.deepEqual(enabledActions(html), [], "unknown result: no editor, no button");
    html = renderPanel(input(applied(baseStates()), { draft: { slot: 3, setting: "power", value: "7900" } }));
    assert.deepEqual(enabledActions(html), ["undo", "step", "step", "review", "cancel"], "an outcome and a new draft can show together");
  });

  it("the masked form hides typed text and reduces the numeric draft to its validity, so typing does not rewrite the panel", () => {
    const states = reviewed(baseStates(), 3, "target_soc", "90", "20", "4321", 30);
    const mine: Draft = { slot: 3, setting: "target_soc", value: "90" };
    const a = renderPanel(input(states, { draft: mine, typed: "SET SLOT 3 TAR" }), true);
    const b = renderPanel(input(states, { draft: mine, typed: "SET SLOT 3 TARGET SOC 9" }), true);
    assert.equal(a, b);
    assert.ok(!a.includes("SET SLOT 3 TAR\""));
    const c = renderPanel(input(states, { draft: mine, typed: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" }), true);
    assert.notEqual(a, c, "the gate flip is a change");
    const e1 = renderPanel(input(baseStates(), { draft: { ...mine, value: "9" } }), true);
    const e2 = renderPanel(input(baseStates(), { draft: { ...mine, value: "1" } }), true);
    assert.equal(e1, e2, "two invalid values with the same reason");
    const e3 = renderPanel(input(baseStates(), { draft: { ...mine, value: "90" } }), true);
    assert.notEqual(e1, e3);
    assert.ok(renderPanel(input(states, { draft: mine, typed: "SET" }), false).includes('value="SET"'), "the unmasked form carries the typed text");
  });
});
