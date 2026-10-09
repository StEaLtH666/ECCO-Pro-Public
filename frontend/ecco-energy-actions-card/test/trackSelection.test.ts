// OVW1 `layout: tabbed`: the pure track-selection rules (initial tab priority,
// the cross-track alert, its tone and text) over every display-state pair,
// plus DOM-free structural checks on the component source proving that the
// tabbed render path still classifies BOTH tracks, that the initial tab is
// pinned only once a real state exists, that a tab switch only touches local
// UI state, and that the new module has no regex literal. (This file uses
// no regex literal either: plain string operations only.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  canChooseTrack,
  initialTrack,
  trackRank,
  hiddenTrackAlert,
  alertTone,
  trackName,
  hiddenTrackAlertText,
  type DisplayStateLike,
  type Track,
  type TrackAlert,
} from "../src/trackSelection.ts";

// The priority table from the design (most urgent first). Written out here
// independently of the module so the 9x9 matrix below is checked against the
// spec, not against the implementation's own list.
const PRIORITY: readonly DisplayStateLike[] = [
  "recovery_attention",
  "deferred",
  "busy",
  "active",
  "armed",
  "scheduled",
  "interlocked",
  "ready",
  "unavailable",
];

// ---------------------------------------------------------------------
// initialTrack(): all 81 pairs
// ---------------------------------------------------------------------

test("initialTrack: every one of the 9x9 display-state pairs follows the priority table; ties go to Free Power", () => {
  let pairs = 0;
  for (const fp of PRIORITY) {
    for (const dump of PRIORITY) {
      const expected: Track = PRIORITY.indexOf(dump) < PRIORITY.indexOf(fp) ? "dump_to_grid" : "free_power";
      assert.equal(initialTrack(fp, dump), expected, `fp=${fp} dump=${dump}`);
      pairs += 1;
    }
  }
  assert.equal(pairs, 81);
});

test("initialTrack: ties (including both ready and both unavailable) select Free Power", () => {
  for (const s of PRIORITY) {
    assert.equal(initialTrack(s, s), "free_power", s);
  }
});

test("initialTrack: Dump to Grid recovery attention outranks every Free Power state, and Free Power recovery attention is never displaced", () => {
  for (const fp of PRIORITY) {
    if (fp !== "recovery_attention") assert.equal(initialTrack(fp, "recovery_attention"), "dump_to_grid", fp);
    assert.equal(initialTrack("recovery_attention", fp), "free_power", fp);
  }
});

test("initialTrack: an unavailable Free Power yields to any other Dump to Grid state, and a merely scheduled/armed Dump never displaces a live Free Power state", () => {
  for (const dump of PRIORITY) {
    if (dump !== "unavailable") assert.equal(initialTrack("unavailable", dump), "dump_to_grid", dump);
  }
  for (const fp of ["active", "busy", "deferred", "recovery_attention"] as const) {
    assert.equal(initialTrack(fp, "scheduled"), "free_power", fp);
    assert.equal(initialTrack(fp, "armed"), "free_power", fp);
  }
});

test("canChooseTrack: false only while BOTH tracks are unavailable (device offline / entities not registered yet); any real state on either side allows the choice", () => {
  let pairs = 0;
  for (const fp of PRIORITY) {
    for (const dump of PRIORITY) {
      assert.equal(canChooseTrack(fp, dump), fp !== "unavailable" || dump !== "unavailable", `fp=${fp} dump=${dump}`);
      pairs += 1;
    }
  }
  assert.equal(pairs, 81);
  assert.equal(canChooseTrack("unavailable", "unavailable"), false);
  // the unconfigured Dump preview shell ranks "unavailable": Free Power alone decides, as soon as it has a state
  assert.equal(canChooseTrack("ready", "unavailable"), true);
  assert.equal(canChooseTrack("unavailable", "recovery_attention"), true);
});

test("trackRank: strictly increasing along the priority table; an unknown word ranks last", () => {
  for (let i = 1; i < PRIORITY.length; i++) {
    assert.ok(trackRank(PRIORITY[i - 1]!) < trackRank(PRIORITY[i]!), `${PRIORITY[i - 1]} before ${PRIORITY[i]}`);
  }
  assert.ok(trackRank("bogus" as DisplayStateLike) > trackRank("unavailable"));
  assert.equal(initialTrack("bogus" as DisplayStateLike, "unavailable"), "dump_to_grid");
});

// ---------------------------------------------------------------------
// hiddenTrackAlert() / alertTone(): every display state
// ---------------------------------------------------------------------

const EXPECTED_ALERT: Record<DisplayStateLike, TrackAlert> = {
  recovery_attention: "fault",
  deferred: "warning",
  busy: "warning",
  active: "info",
  armed: "none",
  scheduled: "none",
  interlocked: "none",
  ready: "none",
  unavailable: "none",
};

test("hiddenTrackAlert: a banner only for a hidden active / busy / deferred / recovery_attention track", () => {
  for (const s of PRIORITY) {
    assert.equal(hiddenTrackAlert(s), EXPECTED_ALERT[s], s);
  }
  const withBanner = PRIORITY.filter((s) => hiddenTrackAlert(s) !== "none").sort();
  assert.deepEqual(withBanner, ["active", "busy", "deferred", "recovery_attention"]);
});

test("alertTone: fault -> fault, warning -> warning, info -> the card accent, none -> no banner", () => {
  assert.equal(alertTone("fault"), "fault");
  assert.equal(alertTone("warning"), "warning");
  assert.equal(alertTone("info"), "accent");
  assert.equal(alertTone("none"), null);
});

test("alertTone(hiddenTrackAlert()) is null for exactly the five states that show in the chip only", () => {
  const chipOnly = PRIORITY.filter((s) => alertTone(hiddenTrackAlert(s)) === null).sort();
  assert.deepEqual(chipOnly, ["armed", "interlocked", "ready", "scheduled", "unavailable"]);
});

// ---------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------

test("trackName spells the two product names exactly as the tiles do", () => {
  assert.equal(trackName("free_power"), "Free Power");
  assert.equal(trackName("dump_to_grid"), "Dump to Grid");
});

test("hiddenTrackAlertText: name and state label, then the literal firmware status text when there is one", () => {
  assert.equal(hiddenTrackAlertText("Dump to Grid", "Active", "ACTIVE - VERIFIED OK; target 1100W export"), "Dump to Grid: Active - ACTIVE - VERIFIED OK; target 1100W export");
  assert.equal(hiddenTrackAlertText("Free Power", "Attention Needed", undefined), "Free Power: Attention Needed");
  assert.equal(hiddenTrackAlertText("Free Power", "Working", "   "), "Free Power: Working");
  assert.equal(hiddenTrackAlertText("Free Power", "Working", "  RESTORING - step 2  "), "Free Power: Working - RESTORING - step 2");
});

// ---------------------------------------------------------------------
// Structural checks on the component source (DOM-free). The full render
// path is exercised by the browser matrix; these pin the safety-relevant
// shape of the tabbed code so a regression is caught without a DOM.
// ---------------------------------------------------------------------

const MAIN = readFileSync(new URL("../src/ecco-energy-actions-card.ts", import.meta.url), "utf-8");
const MODULE = readFileSync(new URL("../src/trackSelection.ts", import.meta.url), "utf-8");

/** The source text of one class member, from its declaration to the next member / section banner. */
function member(name: string): string {
  const starts = [`\n  private ${name}(`, `\n  protected ${name}(`]
    .map((marker) => MAIN.indexOf(marker))
    .filter((i) => i >= 0);
  assert.ok(starts.length > 0, `${name} not found`);
  const start = Math.min(...starts);
  const ends = ["\n  private ", "\n  protected ", "\n  // ----", "\n  static "]
    .map((marker) => MAIN.indexOf(marker, start + 10))
    .filter((i) => i >= 0);
  return MAIN.slice(start, Math.min(...ends));
}

test("render() branches to the tabbed layout only on `layout: tabbed`; any other value keeps the side-by-side grid", () => {
  const render = member("render");
  assert.equal(render.split('this._config.layout === "tabbed"').length, 2);
  assert.ok(render.includes('if (this._config.layout === "tabbed") return this._renderTabbed(title);'));
  assert.ok(render.includes("${this._renderFreePowerTile()}") && render.includes("${this._renderDumpToGridTile()}"));
  assert.equal(MAIN.split("layout ===").length, 3, "the layout key is read in render() and willUpdate() only");
});

test("tabbed rendering classifies BOTH tracks unconditionally: _trackSummary runs both classifier helpers and never looks at the selected tab", () => {
  const summary = member("_trackSummary");
  assert.ok(summary.includes("this._freePowerVisualStateForInterlock()"));
  assert.ok(summary.includes("this._dumpVisualStateForInterlock()"));
  assert.ok(!summary.includes("this._track"), "_trackSummary must not depend on the selected track");
  // the same overlays the tiles apply, in the same order (schedule, then interlock)
  assert.ok(summary.includes("resolveDisplayState(fpVisual, classifySchedule("));
  assert.ok(summary.includes("resolveDumpDisplayState(dumpVisual,"));
  assert.ok(summary.includes("isInterlocked(fpVisual, dumpVisual)") && summary.includes("isInterlocked(dumpVisual, fpVisual)"));
  assert.ok(summary.includes("this._labelFor(state)") && summary.includes("dumpDisplayStateLabel(state)"));
  assert.ok(!summary.includes("_callService"));

  const tabbed = member("_renderTabbed");
  assert.ok(tabbed.includes("const tracks = this._trackSummary();"), "both tracks are summarised before anything is rendered");
  assert.ok(tabbed.includes("this._renderFreePowerTile()") && tabbed.includes("this._renderDumpToGridTile()"));
  assert.ok(tabbed.includes('role="tablist"') && tabbed.split('role="tab"').length === 3);
  assert.ok(tabbed.includes("hiddenTrackAlert(hidden.state)") && tabbed.includes("hiddenTrackAlertText("));
  assert.ok(!tabbed.includes("_callService") && !tabbed.includes("callService"), "the tabbed shell issues no service call");

  const willUpdate = member("willUpdate");
  assert.ok(willUpdate.includes("this._track === null") && willUpdate.includes("initialTrack(tracks.fp.state, tracks.dump.state)"));
  assert.equal(MAIN.split("initialTrack(").length, 3, "initialTrack is called from willUpdate (pins) and _renderTabbed (provisional) only");
});

test("the initial tab is pinned only once a track has a real state: the willUpdate pin is guarded by canChooseTrack over the same two states it then ranks", () => {
  const willUpdate = member("willUpdate");
  const guard = "if (canChooseTrack(tracks.fp.state, tracks.dump.state)) {";
  const pin = "this._track = initialTrack(tracks.fp.state, tracks.dump.state);";
  const guardAt = willUpdate.indexOf(guard);
  const pinAt = willUpdate.indexOf(pin);
  assert.ok(guardAt >= 0 && pinAt > guardAt, "the pin sits inside the canChooseTrack guard");
  assert.ok(!willUpdate.slice(guardAt, pinAt).includes("}"), "nothing closes the guard before the pin");
  assert.equal(MAIN.split("canChooseTrack(").length, 2, "the guard is the only canChooseTrack call site");
  // the provisional render path never pins: _renderTabbed only reads _track
  const tabbed = member("_renderTabbed");
  assert.ok(tabbed.includes("this._track ?? initialTrack(tracks.fp.state, tracks.dump.state)"));
  assert.ok(!tabbed.includes("this._track ="));
});

test("switching tracks cancels BOTH pending End & Restore confirmations and touches nothing else", () => {
  const select = member("_selectTrack");
  assert.ok(select.includes("if (this._confirmTimer) clearTimeout(this._confirmTimer);"));
  assert.ok(select.includes("if (this._confirmDumpTimer) clearTimeout(this._confirmDumpTimer);"));
  assert.ok(select.includes("this._confirmEndRestore = false;") && select.includes("this._confirmEndDump = false;"));
  assert.ok(select.includes("this._track = track;"));
  for (const forbidden of ["_mode", "_dumpMode", "_pending", "_callService", "hass", "_nowMs", "write_enable", "end_restore"]) {
    assert.ok(!select.includes(forbidden), `_selectTrack must not touch ${forbidden}`);
  }
  // the only writers of _track are the pin in willUpdate and the tab click handler
  assert.equal(MAIN.split("this._track = ").length, 3);
  assert.equal(MAIN.split("this._selectTrack(").length, 4, "two tabs + the alert banner's Show button");
});

test("the Dump LATER panel and schedule bodies are untouched by the tabbed layout (no `_track` reference)", () => {
  for (const name of ["_renderLaterPanel", "_renderDumpLaterPanel", "_renderScheduleBanner", "_renderDumpScheduleBanner"]) {
    assert.ok(!member(name).includes("_track"), name);
  }
});

test("trackSelection.ts is pure: no Lit, no DOM, no hass, type-only imports, and no regex literal", () => {
  // code only (comment lines dropped) for the vocabulary checks - the header comment legitimately says what the module does NOT use
  const isComment = (l: string): boolean => {
    const t = l.trimStart();
    return t.startsWith("//") || t.startsWith("/*") || t.startsWith("*");
  };
  const code = MODULE.split("\n")
    .filter((l) => !isComment(l))
    .join("\n");
  assert.ok(!code.includes('from "lit'));
  assert.ok(!code.includes("document") && !code.includes("window") && !code.includes("hass"));
  const imports = code.split("\n").filter((l) => l.startsWith("import "));
  assert.ok(imports.length >= 1 && imports.every((l) => l.startsWith("import type ")), imports.join(" | "));
  // the whole file for the regex-literal scan: the repository suites parse comments too
  assert.ok(!MODULE.includes(".test(") && !MODULE.includes("= /") && !MODULE.includes("RegExp"), "no regex literal in the module");
  // the retired fixed Dump ceiling must not reappear anywhere in the card folder; spelled with a separator so the bare token never appears here either
  const legacyCeiling = String(3_000);
  assert.ok(!MODULE.includes(legacyCeiling) && !MAIN.includes(legacyCeiling));
});
