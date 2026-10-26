// Pure-logic tests: configuration, the ACS1 contract parsers, the phrase, the editor state machine, eligibility, Undo and spacing.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ACK_PHRASE,
  APPLY_SPACING_S,
  EDITABLE,
  H_IN_FLIGHT,
  H_LOCK,
  H_OWNER_EDIT,
  H_PLAN,
  H_RESERVE,
  H_RESULT,
  SCRIPT_APPLY,
  SCRIPT_REVIEW,
  activeSlot,
  applyCall,
  acknowledgeCall,
  classifyResult,
  configAgeSeconds,
  context,
  displayValue,
  dongleIds,
  editorView,
  formatLondonWall,
  isClockChangeNight,
  londonMinutes,
  londonParts,
  londonWallToUtcMs,
  normalizeConfig,
  parseApplied,
  parseHHMM,
  parseOwnerEdit,
  parsePlan,
  phraseFor,
  phraseMatches,
  planMatchesDraft,
  progressSteps,
  rawFromDisplay,
  referencedIds,
  refusalHint,
  reviewCall,
  slotIds,
  slotView,
  spacingRemaining,
  startsAscending,
  undoFor,
  validateDraft,
} from "../src/model.ts";
import type { Plan, SlotView, StatesLike } from "../src/types.ts";
import { ALL_SLOT_IDS, APPLIED_TEXT, NOW, OWNER_EDIT_TEXT, PREFIX, applied, baseStates, config, ent, frontendLike, iso, reviewed, wall, withEntity, withState } from "./fixtures.ts";

const CFG = config();
const D = dongleIds(PREFIX);

function views(states: StatesLike, nowMs = NOW): { ctx: ReturnType<typeof context>; slots: SlotView[]; editor: ReturnType<typeof editorView> } {
  const now = new Date(nowMs);
  const ctx = context(states, CFG, nowMs, now);
  const slots: SlotView[] = [];
  for (let n = 1; n <= 6; n++) slots.push(slotView(states, CFG, n, nowMs, londonMinutes(nowMs), ctx));
  return { ctx, slots, editor: editorView(states, CFG, nowMs, now, ctx, slots) };
}

describe("configuration", () => {
  it("defaults, and refuses unknown or malformed options", () => {
    assert.deepEqual(normalizeConfig({ type: "custom:ecco-tou-settings-card" }), { title: "Time of Use Schedule", entity_prefix: "ecco_clock_dongle", max_age_configuration_s: 300 });
    assert.equal(normalizeConfig({ entity_prefix: "site_b", title: "T", max_age_configuration_s: 60 }).entity_prefix, "site_b");
    assert.throws(() => normalizeConfig({ apply_spacing_s: 0 }), /unknown option 'apply_spacing_s'/);
    assert.throws(() => normalizeConfig({ allow_start_time: true }), /unknown option/);
    assert.throws(() => normalizeConfig({ entity_prefix: "Bad Slug" }), /entity_prefix/);
    assert.throws(() => normalizeConfig({ entity_prefix: "a__b" }), /entity_prefix/);
    assert.throws(() => normalizeConfig({ max_age_configuration_s: 1 }), /max_age_configuration_s/);
    assert.throws(() => normalizeConfig({ title: "x".repeat(121) }), /title/);
    assert.throws(() => normalizeConfig(null), /mapping/);
    assert.throws(() => normalizeConfig([]), /mapping/);
  });

  it("the spacing rule is a fixed constant (owner decision D5)", () => {
    assert.equal(APPLY_SPACING_S, 300);
  });

  it("entity ids follow the device slug; helper ids never do", () => {
    const ids = referencedIds("site_b");
    assert.ok(ids.includes("sensor.site_b_ecco_timezone3_power"));
    assert.ok(ids.includes("input_text.ecco_cfg_edit_review"));
    assert.ok(ids.includes("script.ecco_cfg_apply_tou_slot_setting"));
    assert.ok(!ids.some((i) => i.includes("site_b_ecco_cfg")));
    assert.equal(new Set(ids).size, ids.length);
    assert.deepEqual(slotIds("x", 6), {
      time: "sensor.x_ecco_timezone6_time", power: "sensor.x_ecco_timezone6_power", soc: "sensor.x_ecco_timezone6_soc",
      charge: "sensor.x_ecco_timezone6_charge", mode: "sensor.x_ecco_timezone6_mode", flags: "sensor.x_ecco_timezone6_raw_flags",
    });
  });
});

describe("the ACS1 contract: plan record, result text, phrase", () => {
  it("parses the six-field plan record and refuses everything else", () => {
    const p = parsePlan("3|target_soc|90|4321|1761400000|20");
    assert.deepEqual(p, { slot: 3, setting: "target_soc", want: "90", code: "4321", reviewedAt: 1761400000, before: "20" });
    assert.deepEqual(parsePlan("6|charge_source|Grid|0007|1761400000|None")?.want, "Grid");
    assert.deepEqual(parsePlan("1|start_time|930|0007|1761400000|900")?.setting, "start_time");
    for (const bad of [null, "used", "", "3|target_soc|90|4321|1761400000", "7|target_soc|90|4321|1|20", "3|voltage|90|4321|1|20",
      "3|target_soc|90|43|1|20", "3|target_soc|ninety|4321|1|20", "3|charge_source|Generator|4321|1|None", "3|target_soc|90|4321|0|20"]) {
      assert.equal(parsePlan(bad), null, String(bad));
    }
  });

  it("classifies the result text by its exact prefix; anything else is unknown (fail closed)", () => {
    assert.equal(classifyResult("REVIEW REFUSED - x; nothing written").kind, "review_refused");
    assert.equal(classifyResult("REVIEWED - slot 3 ...").kind, "reviewed");
    assert.equal(classifyResult("REFUSED - the review has expired (10 minutes); review again; nothing written").kind, "refused");
    assert.equal(classifyResult("IN PROGRESS - slot 3 target SOC 20 % -> 90 %: waiting for a fresh configuration read").kind, "in_progress");
    assert.equal(classifyResult(APPLIED_TEXT).kind, "applied");
    assert.equal(classifyResult("FAILED - the firmware refused the Apply (REJECTED - bus busy); nothing written (counter and later reads agree)").kind, "failed");
    assert.equal(classifyResult("UNCERTAIN - firmware: ...").kind, "uncertain");
    assert.equal(classifyResult("ACKNOWLEDGED - the owner checked the TOU slots; edits unlocked").kind, "acknowledged");
    assert.equal(classifyResult(null).kind, "none");
    assert.equal(classifyResult("APPLIED - slot 3").kind, "unknown");
    assert.equal(classifyResult("applied and verified - x").kind, "unknown");
    assert.equal(classifyResult("REVIEWED-").kind, "unknown");
  });

  it("builds exactly the phrase the Apply script expects, for every setting", () => {
    const plan = (setting: Plan["setting"], want: string): Plan => ({ slot: 3, setting, want, code: "4321", reviewedAt: 1, before: "x" });
    assert.equal(phraseFor(plan("target_soc", "90")), "SET SLOT 3 TARGET SOC 90 REVIEW 4321");
    assert.equal(phraseFor(plan("power", "7900")), "SET SLOT 3 POWER 7900 W REVIEW 4321");
    assert.equal(phraseFor(plan("charge_source", "Grid")), "SET SLOT 3 CHARGE SOURCE GRID REVIEW 4321");
    assert.equal(phraseFor(plan("charge_source", "None")), "SET SLOT 3 CHARGE SOURCE NONE REVIEW 4321");
    assert.equal(phraseFor(plan("start_time", "930")), "SET SLOT 3 START 09:30 REVIEW 4321");
    const p = plan("power", "7900");
    assert.ok(phraseMatches("SET SLOT 3 POWER 7900 W REVIEW 4321", p));
    for (const wrong of ["set slot 3 power 7900 w review 4321", "SET SLOT 3 POWER 7900 W REVIEW 4321 ", " SET SLOT 3 POWER 7900 W REVIEW 4321",
      "SET SLOT 3 POWER 7900W REVIEW 4321", "SET SLOT 3 POWER 7900 W REVIEW 4322", "SET SLOT 2 POWER 7900 W REVIEW 4321", ""]) {
      assert.ok(!phraseMatches(wrong, p), wrong);
    }
  });

  it("display forms round-trip to raw values", () => {
    assert.equal(displayValue("target_soc", "90"), "90 %");
    assert.equal(displayValue("power", "7900"), "7900 W");
    assert.equal(displayValue("start_time", "930"), "09:30");
    assert.equal(displayValue("start_time", "25"), "00:25");
    assert.equal(displayValue("charge_source", "Grid"), "Grid");
    assert.equal(rawFromDisplay("target_soc", "90 %"), "90");
    assert.equal(rawFromDisplay("power", "7900 W"), "7900");
    assert.equal(rawFromDisplay("start_time", "09:30"), "930");
    assert.equal(rawFromDisplay("charge_source", "None"), "None");
    assert.equal(rawFromDisplay("power", "7900"), null);
    assert.equal(rawFromDisplay("charge_source", "Generator"), null);
    assert.equal(parseHHMM("?2475"), null);
    assert.equal(parseHHMM("24:00"), null);
    assert.equal(parseHHMM("00:25"), 25);
  });

  it("parses the APPLIED AND VERIFIED text and the owner-edit record, and refuses mismatched registers", () => {
    assert.deepEqual(parseApplied(APPLIED_TEXT), { slot: 3, setting: "target_soc", before: "20", after: "90" });
    assert.deepEqual(parseApplied("APPLIED AND VERIFIED - slot 6 charge source Grid -> None: firmware readback and ..."), { slot: 6, setting: "charge_source", before: "Grid", after: "None" });
    assert.deepEqual(parseApplied("APPLIED AND VERIFIED - slot 1 power 8000 W -> 7900 W: x"), { slot: 1, setting: "power", before: "8000", after: "7900" });
    assert.equal(parseApplied("APPLIED AND VERIFIED - slot 1 voltage 1 -> 2: x"), null);
    assert.equal(parseApplied("FAILED - x"), null);
    assert.deepEqual(parseOwnerEdit(OWNER_EDIT_TEXT), { slot: 3, setting: "target_soc", before: "20", after: "90" });
    assert.equal(parseOwnerEdit("2026-10-25 13:55:10 slot 3 target SOC (register 271) 20 % -> 90 % (owner, Advanced Configuration)"), null, "register must be 267+slot");
    assert.equal(parseOwnerEdit("2026-10-25 13:55:10 slot 3 target SOC (register 270) 20 % -> 90 % (owner, Manual Controls)"), null);
    assert.equal(parseOwnerEdit(null), null);
  });

  it("describes the three allowed calls and nothing else", () => {
    assert.deepEqual(reviewCall({ slot: 3, setting: "target_soc", value: "90" }), {
      domain: "script", service: "turn_on", data: { entity_id: SCRIPT_REVIEW, variables: { slot: 3, setting: "target_soc", value: 90 } },
    });
    assert.deepEqual(reviewCall({ slot: 6, setting: "charge_source", value: "None" }).data.variables, { slot: 6, setting: "charge_source", value: "None" });
    assert.deepEqual(applyCall("SET SLOT 3 TARGET SOC 90 REVIEW 4321").data, { entity_id: SCRIPT_APPLY, variables: { confirmation: "SET SLOT 3 TARGET SOC 90 REVIEW 4321" } });
    assert.equal(acknowledgeCall(ACK_PHRASE).data.variables.confirmation, "I HAVE CHECKED THE TOU SLOTS");
  });
});

describe("clock-change nights and the active slot", () => {
  it("00:00-03:00 Europe/London on the last Sunday of March and October only, read on the London clock (zone-independent instants)", () => {
    assert.ok(isClockChangeNight(Date.UTC(2026, 9, 25, 0, 30)), "01:30 BST, the first pass");
    assert.ok(isClockChangeNight(Date.UTC(2026, 9, 25, 1, 30)), "01:30 GMT, the second pass");
    assert.ok(isClockChangeNight(Date.UTC(2026, 9, 24, 23, 0)), "00:00 BST on the 25th (still the 24th in UTC)");
    assert.ok(!isClockChangeNight(Date.UTC(2026, 9, 25, 3, 0)), "03:00 GMT");
    assert.ok(!isClockChangeNight(Date.UTC(2026, 9, 18, 0, 0)), "18 October is a Sunday before the 25th");
    assert.ok(!isClockChangeNight(Date.UTC(2026, 9, 26, 1, 0)), "Monday");
    assert.ok(isClockChangeNight(Date.UTC(2026, 2, 29, 1, 30)), "02:30 BST on 29 March 2026, the last Sunday of March");
    assert.ok(isClockChangeNight(Date.UTC(2026, 2, 29, 0, 30)), "00:30 GMT on 29 March");
    assert.ok(!isClockChangeNight(Date.UTC(2026, 3, 26, 0, 0)), "April");
    assert.ok(!isClockChangeNight(Date.UTC(2026, 9, 24, 22, 59)), "23:59 BST on Saturday the 24th");
  });

  it("O-1: the slot clock and the clock-change rule are London's whatever the process zone", () => {
    assert.equal(londonMinutes(Date.UTC(2026, 6, 1, 11, 0)), 12 * 60, "BST");
    assert.equal(londonMinutes(Date.UTC(2026, 0, 15, 12, 0)), 12 * 60, "GMT");
    assert.equal(londonMinutes(Date.UTC(2026, 9, 24, 23, 30)), 30, "00:30 BST on the 25th");
    assert.deepEqual(londonParts(Date.UTC(2026, 9, 25, 0, 30)), { year: 2026, month: 10, day: 25, hour: 1, minute: 30, second: 0, weekday: 0 });
    const original = process.env.TZ;
    try {
      for (const z of ["America/New_York", "Asia/Tokyo", "UTC", "Europe/London"]) {
        process.env.TZ = z;
        assert.equal(londonMinutes(NOW), 14 * 60, z);
        assert.ok(isClockChangeNight(Date.UTC(2026, 9, 25, 0, 30)), z);
        assert.equal(views(baseStates()).slots.filter((v) => v.active).map((v) => v.slot).join(), "3", `${z}: 14:00 London lies in slot 3`);
      }
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });

  it("finds the active slot across midnight for the wrapping layout, and knows the layout is not ascending", () => {
    const starts = [30, 330, 720, 995, 1320, 25];
    assert.equal(activeSlot(starts, 27), 6);
    assert.equal(activeSlot(starts, 25), 6);
    assert.equal(activeSlot(starts, 35), 1);
    assert.equal(activeSlot(starts, 23 * 60), 5);
    assert.equal(activeSlot(starts, 12 * 60), 3);
    assert.equal(activeSlot([30, 330, 720, 995, 1320, null], 100), null);
    assert.ok(!startsAscending(starts));
    assert.ok(startsAscending([30, 330, 720, 995, 1320, 1400]));
    assert.equal(activeSlot([30, 330, 720, 995, 1320, 1400], 1410), 6);
    assert.equal(activeSlot([30, 330, 720, 995, 1320, 1400], 10), 6, "slot 6 runs past midnight to slot 1's start");
  });
});

describe("blockers, eligibility and draft validation", () => {
  it("the idle, healthy world has no blocker and every editable field is editable; the SOC floor is max(shutdown, reserve)", () => {
    const { ctx, slots } = views(baseStates());
    assert.deepEqual(ctx.blockers, []);
    assert.equal(ctx.socFloor, 20);
    for (const v of slots) {
      assert.ok(v.fresh, `slot ${v.slot} fresh`);
      assert.ok(v.eligibility.target_soc.allowed);
      assert.ok(v.eligibility.power.allowed);
      assert.ok(v.eligibility.charge_source.allowed);
    }
    assert.equal(slots[5]?.end.text, "00:30", "slot 6 ends at slot 1's start");
    assert.equal(slots.filter((v) => v.active).map((v) => v.slot).join(), "3", "14:00 lies in slot 3 (12:00-16:35)");
  });

  it("each unsafe state is a named blocker, in the status line's priority order", () => {
    const cases: [string, (s: StatesLike) => StatesLike][] = [
      ["locked", (s) => withState(s, H_LOCK, "on")],
      ["busy", (s) => withState(s, SCRIPT_APPLY, "on")],
      ["busy", (s) => withState(s, H_IN_FLIGHT, "on")],
      ["free_power", (s) => withState(s, D.fpSnapshot, "on")],
      ["dump_to_grid", (s) => withState(s, D.dgOp, "on")],
      ["offline", (s) => withState(s, D.configOnline, "off")],
      ["offline", (s) => withState(s, D.cacheValid, "off")],
      ["config_stale", (s) => withState(s, D.configUpdate, wall(200_000), 200_000)],
      ["config_stale", (s) => withState(s, D.configUpdate, "garbage")],
      ["config_stale", (s) => withState(s, D.configUpdate, iso(20_000), 20_000)],
      ["heartbeat", (s) => withState(s, D.heartbeatAge, "75")],
      ["heartbeat", (s) => withEntity(s, D.heartbeatAge, undefined)],
      ["supervision", (s) => withState(s, D.supervisionStable, "off")],
      ["write_in_progress", (s) => withState(s, D.writeInProgress, "on")],
      ["rtc", (s) => withState(s, D.rtcInProgress, "on")],
      ["armed", (s) => withState(s, D.writeEnable, "on")],
      ["armed", (s) => withState(s, D.dgRecoveryArm, "on")],
      ["scheduled", (s) => withState(withState(s, "input_boolean.ecco_free_power_schedule_armed", "on"), "input_datetime.ecco_free_power_schedule_start", wall(-600_000))],
    ];
    for (const [code, mutate] of cases) {
      const { ctx, slots } = views(mutate(baseStates()));
      assert.equal(ctx.blockers[0]?.code, code, code);
      assert.ok(!slots[2]?.eligibility.target_soc.allowed, `${code} disables the pen`);
      assert.equal(slots[2]?.eligibility.target_soc.reason, ctx.blockers[0]?.text);
    }
    // priority: the lock outranks everything else
    const { ctx } = views(withState(withState(baseStates(), D.fpActive, "on"), H_LOCK, "on"));
    assert.equal(ctx.blockers.map((b) => b.code).join(), "locked,free_power");
    // a scheduled start far away is not a blocker; one with an unreadable start time is; the start is a London wall time (O-1), the same in every zone
    assert.deepEqual(views(withState(baseStates(), "input_boolean.ecco_dump_to_grid_schedule_armed", "on")).ctx.blockers, []);
    assert.equal(views(withState(withState(baseStates(), "input_boolean.ecco_dump_to_grid_schedule_armed", "on"), "input_datetime.ecco_dump_to_grid_schedule_start", "unknown")).ctx.blockers[0]?.code, "scheduled");
    const armedSoon = withState(withState(baseStates(), "input_boolean.ecco_dump_to_grid_schedule_armed", "on"), "input_datetime.ecco_dump_to_grid_schedule_start", wall(-600_000));
    const armedLater = withState(withState(baseStates(), "input_boolean.ecco_dump_to_grid_schedule_armed", "on"), "input_datetime.ecco_dump_to_grid_schedule_start", wall(-1_200_000));
    const originalTz = process.env.TZ;
    try {
      for (const z of ["America/New_York", "Asia/Tokyo", "UTC"]) {
        process.env.TZ = z;
        assert.equal(views(armedSoon).ctx.blockers[0]?.code, "scheduled", z);
        assert.deepEqual(views(armedLater).ctx.blockers, [], z);
      }
    } finally {
      if (originalTz === undefined) delete process.env.TZ;
      else process.env.TZ = originalTz;
    }
  });

  it("the shadow latch is the gate's to judge: the card only explains the Review's own refusal text", () => {
    assert.ok(refusalHint("REVIEW REFUSED - supervision not stable or a failback episode is open; nothing written"));
    assert.equal(refusalHint("REVIEW REFUSED - Free Power owns the TOU settings (active, starting or restore owed); nothing written"), null);
    assert.ok(!referencedIds(PREFIX).some((id) => /shadow|fallback|failback/.test(id)), "no reserved or decoder id is read");
  });

  it("the clock-change night is a blocker on the London clock (zone-independent instants; H1)", () => {
    const firstPass = Date.UTC(2026, 9, 25, 0, 30);   // 01:30 BST: the poll text is the first reading of the repeated hour
    const b1 = views(baseStates(PREFIX, firstPass), firstPass).ctx.blockers.map((b) => b.code);
    assert.deepEqual(b1, ["clock_change"], String(b1));
    const secondPass = Date.UTC(2026, 9, 25, 1, 30);   // 01:30 GMT: the same wall text reads as the earlier instant (3620 s), so config_stale too, by design
    const b2 = views(baseStates(PREFIX, secondPass), secondPass).ctx.blockers.map((b) => b.code);
    assert.ok(b2.includes("clock_change") && b2.includes("config_stale"), String(b2));
    const after = Date.UTC(2026, 9, 25, 3, 1);
    assert.deepEqual(views(baseStates(PREFIX, after), after).ctx.blockers, []);
  });

  it("per-row eligibility: live power off the 100 W grid, a generator source, missing bounds, unreadable flags, stale values", () => {
    const s3 = slotIds(PREFIX, 3);
    let v = views(withState(baseStates(), s3.power, "2550", 20_000)).slots[2]!;
    assert.ok(!v.eligibility.power.allowed && /not a multiple of 100 W/.test(v.eligibility.power.reason));
    assert.ok(v.eligibility.target_soc.allowed, "a SOC edit on that slot is unaffected");
    v = views(withState(baseStates(), s3.charge, "Generator", 20_000)).slots[2]!;
    assert.ok(!v.eligibility.charge_source.allowed && /only None and Grid/.test(v.eligibility.charge_source.reason));
    v = views(withEntity(baseStates(), H_RESERVE, undefined)).slots[2]!;
    assert.ok(!v.eligibility.target_soc.allowed && /reserve/.test(v.eligibility.target_soc.reason));
    assert.ok(v.eligibility.power.allowed);
    v = views(withState(baseStates(), s3.flags, "unavailable", 20_000)).slots[2]!;
    assert.ok(!v.eligibility.power.allowed && /raw flags/.test(v.eligibility.power.reason));
    v = views(withState(withState(baseStates(), s3.soc, "20", 400_000), D.configUpdate, wall(400_000), 400_000)).slots[2]!;
    assert.ok(!v.fresh && !v.current && !v.eligibility.charge_source.allowed && /not current/.test(v.eligibility.charge_source.reason));
    v = views(withState(baseStates(), s3.time, "?2475", 20_000)).slots[2]!;
    assert.equal(v.start.text, "Unexpected value");
    v = views(withEntity(baseStates(), s3.power, undefined)).slots[2]!;
    assert.equal(v.power.text, "Entity not found");
    assert.ok(!v.eligibility.power.allowed);
  });

  it("drafts are validated against the bounds, the step and the live value", () => {
    const { ctx, slots } = views(baseStates());
    const v3 = slots[2]!;
    assert.ok(validateDraft({ slot: 3, setting: "target_soc", value: "90" }, v3, ctx).allowed);
    assert.match(validateDraft({ slot: 3, setting: "target_soc", value: "19" }, v3, ctx).reason, /20-100 %/);
    assert.match(validateDraft({ slot: 3, setting: "target_soc", value: "101" }, v3, ctx).reason, /20-100 %/);
    assert.match(validateDraft({ slot: 3, setting: "target_soc", value: "20" }, v3, ctx).reason, /No change/);
    assert.match(validateDraft({ slot: 3, setting: "target_soc", value: "9x" }, v3, ctx).reason, /whole number/);
    assert.ok(validateDraft({ slot: 3, setting: "power", value: "7900" }, v3, ctx).allowed);
    assert.match(validateDraft({ slot: 3, setting: "power", value: "7950" }, v3, ctx).reason, /steps of 100/);
    assert.match(validateDraft({ slot: 3, setting: "power", value: "400" }, v3, ctx).reason, /500-8000/);
    assert.match(validateDraft({ slot: 3, setting: "power", value: "8000" }, v3, ctx).reason, /No change/);
    assert.ok(validateDraft({ slot: 3, setting: "charge_source", value: "Grid" }, v3, ctx).allowed);
    assert.match(validateDraft({ slot: 3, setting: "charge_source", value: "None" }, v3, ctx).reason, /No change/);
    assert.match(validateDraft({ slot: 3, setting: "charge_source", value: "Generator" }, v3, ctx).reason, /None or Grid/);
    assert.ok(planMatchesDraft({ slot: 3, setting: "target_soc", want: "90", code: "1", reviewedAt: 1, before: "20" }, { slot: 3, setting: "target_soc", value: " 90" }));
    assert.ok(!planMatchesDraft({ slot: 3, setting: "target_soc", want: "90", code: "1", reviewedAt: 1, before: "20" }, { slot: 3, setting: "power", value: "90" }));
    assert.ok(!planMatchesDraft({ slot: 3, setting: "charge_source", want: "Grid", code: "1", reviewedAt: 1, before: "None" }, { slot: 3, setting: "charge_source", value: "None" }));
  });
});

describe("the editor state machine (derived from entities only)", () => {
  it("maps every helper combination to exactly one state", () => {
    assert.equal(views(baseStates()).editor.state, "IDLE");
    assert.equal(views(withEntity(baseStates(), H_PLAN, undefined)).editor.state, "UNAVAILABLE");
    assert.equal(views(withEntity(baseStates(), SCRIPT_APPLY, undefined)).editor.state, "UNAVAILABLE");
    assert.equal(views(withState(baseStates(), H_LOCK, "on")).editor.state, "LOCKED");
    assert.equal(views(withState(baseStates(), SCRIPT_APPLY, "on")).editor.state, "BUSY");
    assert.equal(views(withState(baseStates(), H_IN_FLIGHT, "on")).editor.state, "BUSY");
    assert.equal(views(withState(baseStates(), H_IN_FLIGHT, "unavailable")).editor.state, "BUSY", "O-4: not-off is in flight, as the scripts test it");
    assert.ok(views(withState(withState(baseStates(), H_LOCK, "on"), H_IN_FLIGHT, "unknown")).editor.inFlight, "O-4: an unknown marker holds Acknowledge");
    assert.equal(views(withState(withState(baseStates(), H_LOCK, "on"), SCRIPT_APPLY, "on")).editor.state, "LOCKED", "the lock outranks busy");
    assert.equal(views(reviewed(baseStates(), 3, "target_soc", "90", "20")).editor.state, "REVIEWED");
    assert.equal(views(withState(baseStates(), H_RESULT, "REVIEW REFUSED - Free Power owns the TOU settings (active, starting or restore owed); nothing written")).editor.state, "OUTCOME");
    assert.equal(views(applied(baseStates())).editor.state, "OUTCOME");
    assert.equal(views(withState(baseStates(), H_RESULT, "UNCERTAIN - firmware: x")).editor.state, "OUTCOME");
    assert.equal(views(withState(baseStates(), H_RESULT, "something new")).editor.state, "OUTCOME");
    assert.equal(views(withState(baseStates(), H_RESULT, "something new")).editor.result.kind, "unknown");
    assert.equal(views(withState(baseStates(), H_RESULT, "unknown")).editor.state, "IDLE");
  });

  it("REVIEWED needs a live plan whose code the REVIEWED text carries, inside the 10 minutes", () => {
    const base = baseStates();
    let s = reviewed(base, 3, "target_soc", "90", "20", "4321", 30);
    let e = views(s).editor;
    assert.equal(e.state, "REVIEWED");
    assert.ok(e.planLive && e.plan?.code === "4321");
    assert.ok(e.planExpiresInS !== null && e.planExpiresInS > 560 && e.planExpiresInS <= 570);
    s = reviewed(base, 3, "target_soc", "90", "20", "4321", 601);
    assert.equal(views(s).editor.state, "OUTCOME", "expired: the REVIEWED text is now just an outcome");
    s = withState(reviewed(base, 3, "target_soc", "90", "20", "4321", 30), H_PLAN, "3|target_soc|90|9999|" + (Math.floor(NOW / 1000) - 30) + "|20");
    assert.equal(views(s).editor.state, "OUTCOME", "a plan whose code the result does not name is not live");
    s = withState(reviewed(base, 3, "target_soc", "90", "20"), H_PLAN, "used");
    assert.equal(views(s).editor.state, "OUTCOME");
    s = withState(reviewed(base, 3, "target_soc", "90", "20"), H_RESULT, "REVIEW REFUSED - x; nothing written");
    e = views(s).editor;
    assert.equal(e.state, "OUTCOME", "a later refusal leaves a stale plan record: the card does not treat it as reviewed");
  });

  it("spacing: five minutes after the last outcome or owner edit, whichever is later", () => {
    const base = baseStates();
    assert.equal(spacingRemaining(base, views(base).editor.result, NOW), 0);
    let s = applied(base, 100);
    assert.ok(Math.abs(spacingRemaining(s, views(s).editor.result, NOW) - 200) < 1);
    s = withState(base, H_RESULT, "FAILED - x; nothing written", 60_000);
    assert.ok(Math.abs(spacingRemaining(s, views(s).editor.result, NOW) - 240) < 1);
    s = withState(withState(base, H_RESULT, "REFUSED - x; nothing written", 10_000), H_OWNER_EDIT, OWNER_EDIT_TEXT, 290_000);
    assert.ok(Math.abs(spacingRemaining(s, views(s).editor.result, NOW) - 10) < 1, "a refusal does not start the timer; the owner edit does");
    s = withState(base, H_OWNER_EDIT, OWNER_EDIT_TEXT, -120_000);
    assert.equal(spacingRemaining(s, views(s).editor.result, NOW), APPLY_SPACING_S, "a timestamp in the future is treated conservatively");
  });

  it("Undo (D6): only after APPLIED AND VERIFIED, with the owner-edit record agreeing and the live field at the post-edit value", () => {
    const ok = applied(baseStates());
    assert.deepEqual(views(ok).editor.undo, { slot: 3, setting: "target_soc", value: "20", from: "90" });
    const s3 = slotIds(PREFIX, 3);
    assert.equal(views(withState(ok, s3.soc, "20", 20_000)).editor.undo, null, "the live value is not the post-edit value");
    assert.equal(views(withState(withState(ok, s3.soc, "90", 400_000), D.configUpdate, wall(400_000), 400_000)).editor.undo, null, "the slot is not current (old value, poll stale)");
    assert.equal(views(withState(ok, H_OWNER_EDIT, "2026-10-25 13:55:10 slot 3 target SOC (register 270) 25 % -> 90 % (owner, Advanced Configuration)")).editor.undo, null, "records disagree on the previous value");
    assert.equal(views(withState(ok, H_OWNER_EDIT, "nonsense")).editor.undo, null);
    assert.equal(views(withState(ok, H_RESULT, "FAILED - x; nothing written")).editor.undo, null);
    const start = withState(withState(baseStates(), H_RESULT, "APPLIED AND VERIFIED - slot 2 start time 05:30 -> 05:35: x"), H_OWNER_EDIT, "2026-10-25 13:55:10 slot 2 start time (register 251) 05:30 -> 05:35 (owner, Advanced Configuration)");
    assert.equal(views(start).editor.undo, null, "start-time edits are never undone from this card");
    const src = withState(withState(withState(baseStates(), H_RESULT, "APPLIED AND VERIFIED - slot 6 charge source Grid -> None: x"), H_OWNER_EDIT, "2026-10-25 13:55:10 slot 6 charge source (register 279) Grid -> None (owner, Advanced Configuration)"), slotIds(PREFIX, 6).charge, "None", 20_000);
    assert.deepEqual(views(src).editor.undo, { slot: 6, setting: "charge_source", value: "Grid", from: "None" });
    assert.equal(undoFor(ok, CFG, { kind: "applied", text: "APPLIED AND VERIFIED - slot 9 power 1 W -> 2 W: x" }, views(ok).slots, views(ok).ctx), null);
  });

  it("the progress strip claims only what its signals have shown", () => {
    const base = withState(withState(baseStates(), SCRIPT_APPLY, "on"), H_IN_FLIGHT, "on");
    let s = withState(base, H_RESULT, "IN PROGRESS - slot 3 target SOC 20 % -> 90 %: waiting for a fresh configuration read");
    let steps = progressSteps(s, CFG, views(s).editor.result);
    assert.deepEqual(steps.map((x) => x.seen), [true, false, false, false, false, false]);
    s = withState(s, D.manualLastResult, "Manual staging loaded from current inverter Slot 3 (cache age 4 s)");
    assert.deepEqual(progressSteps(s, CFG, views(s).editor.result).map((x) => x.seen), [true, true, false, false, false, false]);
    s = withState(s, D.writeEnable, "on");
    assert.deepEqual(progressSteps(s, CFG, views(s).editor.result).map((x) => x.seen), [true, true, true, false, false, false]);
    s = withState(withState(s, D.writeEnable, "off"), D.manualLastResult, "VERIFIED OK - manual Slot 3 (6 registers)");
    steps = progressSteps(s, CFG, views(s).editor.result);
    assert.deepEqual(steps.map((x) => x.seen), [true, true, true, true, true, true]);
    assert.match(steps[4]?.label ?? "", /VERIFIED OK/);
    s = withState(s, D.manualLastResult, "Manual staging loaded from current inverter Slot 2 (x)");
    assert.deepEqual(progressSteps(s, CFG, views(s).editor.result).map((x) => x.seen), [true, false, false, false, false, false], "another slot's Load is not this edit's");
    assert.equal(views(s).editor.progress.length, 6);
    assert.equal(views(baseStates()).editor.progress.length, 0);
  });
});

describe("Window B findings: B1 freshness by poll, S1 spacing after FAILED / UNCERTAIN, S2 blockers gate Undo, O2, O5", () => {
  const S3 = slotIds(PREFIX, 3);

  it("B1: frontend-shaped states (no last_reported, values unchanged for hours) are current while the configuration poll is current", () => {
    const s = frontendLike(baseStates(), ALL_SLOT_IDS, 3 * 3_600_000);
    const { ctx, slots } = views(s);
    assert.deepEqual(ctx.blockers, []);
    for (const v of slots) {
      assert.equal(v.currentBy, "poll", `slot ${v.slot}`);
      assert.ok(v.current && !v.fresh);
      for (const k of EDITABLE) assert.ok(v.eligibility[k].allowed, `slot ${v.slot} ${k}: ${v.eligibility[k].reason}`);
    }
    // the same values with the poll stale: not current, every pen off
    const stale = withState(s, D.configUpdate, wall(400_000), 400_000);
    const { slots: s2 } = views(stale);
    assert.ok(s2.every((v) => v.currentBy === "none" && !v.eligibility.target_soc.allowed));
    // a recent own report keeps the row "current by report" for display; editing still needs the current poll (the check comes first)
    const fresh = withState(stale, S3.time, "12:00", 10_000);
    const v3 = views(withState(withState(withState(withState(fresh, S3.power, "8000", 10_000), S3.soc, "20", 10_000), S3.charge, "None", 10_000), S3.mode, "General", 10_000)).slots[2]!;
    assert.equal(v3.currentBy, "report");
    assert.ok(!v3.eligibility.target_soc.allowed && /not current/.test(v3.eligibility.target_soc.reason));
    // an unavailable value is never current, poll or not
    assert.equal(views(withState(s, S3.soc, "unavailable")).slots[2]?.currentBy, "none");
  });

  it("B1: Undo is offered right after APPLIED AND VERIFIED when the edited field is new and the slot's other fields are old but the poll is current", () => {
    let s = applied(baseStates(), 10);
    s = frontendLike(s, ALL_SLOT_IDS.filter((id) => id !== S3.soc), 3 * 3_600_000);
    s[S3.soc] = { ...(s[S3.soc] as object), last_changed: iso(10_000), last_updated: iso(10_000), state: "90", attributes: { unit_of_measurement: "%" } };
    const e = views(s).editor;
    assert.equal(e.state, "OUTCOME");
    assert.deepEqual(e.undo, { slot: 3, setting: "target_soc", value: "20", from: "90" });
    assert.equal(views(withState(s, D.configUpdate, wall(400_000), 400_000)).editor.undo, null, "poll stale: no Undo");
  });

  it("O5: max_age_configuration_s changes the display label only; eligibility uses the fixed 300 s report limit or the poll", () => {
    const wide = config({ max_age_configuration_s: 86400 });
    let s = baseStates();
    for (const id of Object.values(S3)) s = withState(s, id, (s[id] as { state: string }).state, 7_200_000);
    s = withState(s, D.configUpdate, wall(400_000), 400_000);
    const now = new Date(NOW);
    const ctx = context(s, wide, NOW, now);
    const v = slotView(s, wide, 3, NOW, londonMinutes(NOW), ctx);
    assert.ok(!v.fresh, "display: a wide window never makes a 2 h old row 'live' (capped at 300 s; O-5)");
    assert.ok(!v.current && !v.eligibility.target_soc.allowed, "eligibility: neither a recent report nor a current poll");
    // the same old values under a current poll: current by the poll, still not 'live', editable
    const sPoll = withState(s, D.configUpdate, wall(20_000), 20_000);
    const ctx2 = context(sPoll, wide, NOW, new Date(NOW));
    const v2 = slotView(sPoll, wide, 3, NOW, londonMinutes(NOW), ctx2);
    assert.ok(!v2.fresh && v2.currentBy === "poll" && v2.eligibility.target_soc.allowed);
  });

  it("S1: the 300 s spacing survives a FAILED outcome into the next Review (the in-flight marker's off-stamp)", () => {
    let s = withState(baseStates(), H_RESULT, "FAILED - a safety check changed just before the Apply (no quiet Modbus window was found); nothing written", 20_000);
    s = withState(s, H_IN_FLIGHT, "off", 20_000);
    assert.ok(views(s).editor.spacingRemainingS > 270);
    const r = reviewed(s, 3, "target_soc", "90", "20", "4321", 5);
    const e = views(r).editor;
    assert.equal(e.state, "REVIEWED");
    assert.ok(e.spacingRemainingS > 270, `spacing kept: ${e.spacingRemainingS}`);
  });

  it("S1: UNCERTAIN -> Acknowledge -> Review keeps the spacing; a REFUSED Apply that never set in-flight adds no stamp, even with last_triggered (N1)", () => {
    let s = withState(baseStates(), H_RESULT, "ACKNOWLEDGED - the owner checked the TOU slots; edits unlocked", 40_000);
    s = withState(s, H_IN_FLIGHT, "off", 120_000);
    const r = reviewed(s, 3, "target_soc", "90", "20", "4321", 5);
    assert.ok(Math.abs(views(r).editor.spacingRemainingS - 180) < 1);
    let q = withState(baseStates(), H_RESULT, "REFUSED - the review has expired (10 minutes); review again; nothing written", 10_000);
    assert.equal(views(q).editor.spacingRemainingS, 0, "a refusal before the gate stamps nothing (in-flight untouched two hours ago)");
    q = withEntity(q, SCRIPT_APPLY, ent("off", 10_000, { last_triggered: iso(10_000) }));
    assert.equal(views(q).editor.spacingRemainingS, 0, "Home Assistant stamps last_triggered for a refused run too, so it is deliberately not a spacing stamp");
  });

  it("S2: Undo is not offered while an advisory blocker is set or the slot is ineligible for that setting", () => {
    const ok = applied(baseStates(), 400);
    assert.ok(views(ok).editor.undo);
    assert.equal(views(withState(ok, D.fpActive, "on")).editor.undo, null, "Free Power owns the settings");
    assert.equal(views(withState(ok, D.writeEnable, "on")).editor.undo, null, "an arm is on");
    assert.equal(views(withState(ok, S3.flags, "unavailable")).editor.undo, null, "raw flags unreadable");
    assert.equal(views(withEntity(ok, H_RESERVE, undefined)).editor.undo, null, "the SOC bound's inputs are missing");
    const pw = withState(withState(withState(baseStates(), H_RESULT, "APPLIED AND VERIFIED - slot 3 power 2550 W -> 7900 W: x"), H_OWNER_EDIT, "2026-10-25 13:55:10 slot 3 power (register 258) 2550 W -> 7900 W (owner, Advanced Configuration)"), S3.power, "7900", 20_000);
    assert.equal(views(pw).editor.undo, null, "an undo to a value the Review would refuse (2550 W is not a multiple of 100) is not offered");
  });

  it("O2: an unrecognised or stale IN PROGRESS result closes every pen with its reason", () => {
    for (const text of ["SOMETHING ELSE ENTIRELY", "IN PROGRESS - slot 3 target SOC 20 % -> 90 %: waiting for a fresh configuration read"]) {
      const { ctx, slots } = views(withState(baseStates(), H_RESULT, text));
      assert.ok(ctx.resultProblem);
      assert.ok(slots.every((v) => EDITABLE.every((k) => !v.eligibility[k].allowed && v.eligibility[k].reason === ctx.resultProblem)), text);
    }
    assert.equal(views(baseStates()).ctx.resultProblem, null);
  });
});

describe("Window B S-1: the dongle's Europe/London wall-clock timestamp, in every browser zone", () => {
  const ZONES = ["Europe/London", "America/New_York", "Asia/Tokyo", "UTC", "Pacific/Auckland"];
  const originalTz = process.env.TZ;

  function inZones<T>(fn: () => T): T[] {
    const out: T[] = [];
    try {
      for (const z of ZONES) {
        process.env.TZ = z;
        out.push(fn());
      }
    } finally {
      if (originalTz === undefined) delete process.env.TZ;
      else process.env.TZ = originalTz;
    }
    return out;
  }

  it("parses GMT and BST wall times to the same UTC instant whatever the process zone (Date.parse would not)", () => {
    const cases: [string, string | null][] = [
      ["2026-07-01 12:00:00", "2026-07-01T11:00:00.000Z"],
      ["2026-01-15 12:00:00", "2026-01-15T12:00:00.000Z"],
      ["2026-10-25 00:30:00", "2026-10-24T23:30:00.000Z"],
      ["2026-10-25 02:30:00", "2026-10-25T02:30:00.000Z"],
      ["2026-10-25 01:30:00", "2026-10-25T00:30:00.000Z"],
      ["2026-03-29 00:30:00", "2026-03-29T00:30:00.000Z"],
      ["2026-03-29 02:30:00", "2026-03-29T01:30:00.000Z"],
      ["2026-03-29 01:30:00", null],
      ["2026-10-25T14:00:00Z", null],
      ["2026-10-25 14:00", null],
      ["2026-13-01 00:00:00", null],
      ["2026-10-25 24:00:00", null],
      ["garbage", null],
      ["", null],
      ["Waiting", null],
    ];
    for (const [text, want] of cases) {
      const results = inZones(() => londonWallToUtcMs(text));
      for (const r of results) assert.equal(r === null ? null : new Date(r).toISOString(), want, `${text} -> ${want}`);
    }
    const naive = inZones(() => Date.parse("2026-10-25 14:00:00"));
    assert.ok(new Set(naive).size > 1, "the control: Date.parse of the same text differs by zone, so the zone loop discriminates");
    assert.equal(formatLondonWall(Date.parse("2026-07-01T11:00:00Z")), "2026-07-01 12:00:00");
  });

  it("the configuration age comes from that parse, cross-checked by the entity's UTC last_changed, and fails closed", () => {
    const base = baseStates();
    const ages = inZones(() => configAgeSeconds(base, PREFIX, NOW));
    assert.ok(ages.every((a) => a !== null && Math.abs(a - 20) < 1), String(ages));
    assert.deepEqual(views(base).ctx.blockers, []);
    // the text is fresh but the entity has not changed for 400 s (a stalled poll re-publishing the same text): the larger age counts
    assert.ok(Math.abs((configAgeSeconds(withEntity(base, D.configUpdate, ent(wall(20_000), 400_000)), PREFIX, NOW) ?? 0) - 400) < 1);
    // a future wall time (dongle clock ahead by two minutes): unreadable, every pen off
    assert.equal(configAgeSeconds(withState(base, D.configUpdate, wall(-120_000)), PREFIX, NOW), null);
    assert.equal(views(withState(base, D.configUpdate, wall(-120_000))).ctx.blockers[0]?.code, "config_stale");
    // a stale wall time: its age, and the blocker
    assert.ok(Math.abs((configAgeSeconds(withState(base, D.configUpdate, wall(400_000), 400_000), PREFIX, NOW) ?? 0) - 400) < 1);
    assert.equal(views(withState(base, D.configUpdate, wall(400_000), 400_000)).ctx.blockers[0]?.code, "config_stale");
    // the dongle's boot text, an ISO text, unavailable, missing: unreadable, every pen off
    for (const bad of ["Waiting", iso(20_000), "unavailable", "unknown", ""]) {
      assert.equal(configAgeSeconds(withState(base, D.configUpdate, bad), PREFIX, NOW), null, bad);
      assert.equal(views(withState(base, D.configUpdate, bad)).ctx.blockers[0]?.code, "config_stale", bad);
      assert.match(views(withState(base, D.configUpdate, bad)).ctx.blockers[0]?.text ?? "", /unreadable/, bad);
    }
    assert.equal(configAgeSeconds(withEntity(base, D.configUpdate, undefined), PREFIX, NOW), null);
    // across the autumn clock change: 00:59:50 London is BST (23:59:50Z), an hour and ten seconds before a read at 01:00:10Z (01:00:10 GMT)
    const nowFallBack = Date.parse("2026-10-25T01:00:10Z");
    const s = withEntity(baseStates(PREFIX, nowFallBack), D.configUpdate, ent("2026-10-25 00:59:50", 3620_000, {}, nowFallBack));
    assert.ok(Math.abs((configAgeSeconds(s, PREFIX, nowFallBack) ?? 0) - 3620) < 1);
    // the same text with a last_changed only 20 s old: the wall time still reads 3620 s (the larger age counts; that text is not the repeated hour)
    const s2 = withEntity(baseStates(PREFIX, nowFallBack), D.configUpdate, ent("2026-10-25 00:59:50", 20_000, {}, nowFallBack));
    assert.ok((configAgeSeconds(s2, PREFIX, nowFallBack) ?? 0) > 3000);
    // the repeated hour itself: "01:29:40" read at 01:30:00 GMT (the second pass) resolves to the earlier instant, 3620 s, fails closed
    const secondPass = Date.parse("2026-10-25T01:30:00Z");
    const s3 = withEntity(baseStates(PREFIX, secondPass), D.configUpdate, ent("2026-10-25 01:29:40", 20_000, {}, secondPass));
    assert.ok(Math.abs((configAgeSeconds(s3, PREFIX, secondPass) ?? 0) - 3620) < 1);
    // O-3: padding or a suffix is not the dongle's form and is unreadable, as the backend's parser would refuse it
    for (const padded of [" 2026-10-25 13:59:40", "2026-10-25 13:59:40 ", "2026-10-25 13:59:40Z", " 2026-10-25 13:59:40"]) {
      assert.equal(londonWallToUtcMs(padded), null, JSON.stringify(padded));
    }
  });
});

describe("freshness and value texts", () => {
  it("never shows a missing value as a number, and labels stale slots", () => {
    const s3 = slotIds(PREFIX, 3);
    let v = views(withState(baseStates(), s3.soc, "unavailable")).slots[2]!;
    assert.equal(v.soc.text, "Unavailable");
    assert.equal(v.soc.numeric, null);
    v = views(withState(baseStates(), s3.power, "lots")).slots[2]!;
    assert.equal(v.power.text, "Unexpected value");
    v = views(withEntity(baseStates(), s3.mode, ent("General", 900_000))).slots[2]!;
    assert.ok(!v.fresh && v.ageSeconds !== null && v.ageSeconds >= 900);
    assert.equal(v.currentBy, "poll", "old but unchanged, poll current");
    v = views(withEntity(baseStates(), s3.mode, { state: "General" })).slots[2]!;
    assert.equal(v.ageSeconds, null, "no timestamp: freshness cannot be verified");
    assert.ok(!v.fresh);
    assert.equal(v.currentBy, "poll", "a value without any timestamp is still current by the poll when available");
  });
});
