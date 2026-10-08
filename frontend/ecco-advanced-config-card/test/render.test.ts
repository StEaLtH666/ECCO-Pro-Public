import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { CATALOGUE } from "../src/catalogue.generated.ts";
import { buildGlobalPowerView, emptyFilter, entityId, filterItems, groupBySection, resolveValue } from "../src/model.ts";
import {
  esc,
  renderFilters,
  renderGlobalPower,
  renderItem,
  renderItemDetails,
  renderResults,
  renderShell,
  renderSummary,
} from "../src/render.ts";
import { MOBILE_BREAKPOINT_PX, STYLES, TOUCH_TARGET_PX } from "../src/styles.ts";
import type { CatalogueItem, HassEntityLike, ValueView } from "../src/types.ts";
import { GP_MOCK_W, NOW, PREFIX, config, entityOf, iso, item, mockStates, withEntity } from "./fixtures.ts";

const CFG = config();
const ALLOWED_ACTIONS = new Set(["search", "toggle-filter", "clear-filters", "toggle-item"]);

function fresh(state: unknown): HassEntityLike {
  const ts = iso(5000);
  return { state, attributes: {}, last_changed: ts, last_updated: ts, last_reported: ts };
}

function allValues(states = mockStates()): Map<string, ValueView> {
  return new Map(CATALOGUE.items.map((i) => [i.id, resolveValue(i, states, CATALOGUE, CFG, NOW)]));
}

function actions(html: string): string[] {
  return [...html.matchAll(/data-action="([^"]*)"/g)].map((m) => m[1] ?? "");
}

/** The whole card as rendered with every section expanded and a filter active. */
function wholeCard(): string {
  const states = mockStates();
  const values = allValues(states);
  const f = emptyFilter();
  f.statuses.add("LOCKED");
  return [
    renderShell("Advanced", STYLES, CATALOGUE, "footer"),
    renderGlobalPower(buildGlobalPowerView(CATALOGUE, states, CFG, NOW)),
    renderFilters(CATALOGUE, f),
    renderSummary(165, 165),
    renderResults(groupBySection(CATALOGUE, CATALOGUE.items), values, new Set(CATALOGUE.items.map((i) => i.id))),
  ].join("\n");
}

function hostileItem(): CatalogueItem {
  const base = JSON.parse(JSON.stringify(item("battery_control_mode"))) as CatalogueItem;
  const x = '<img src=x onerror="alert(1)">';
  return {
    ...base,
    id: `evil"><script>alert(1)</script>`,
    name: `Name ${x}`,
    description: `Desc ${x}`,
    explanation: `Expl ${x}`,
    lock_reason: `Lock ${x}`,
    interactions: [`Inter ${x}`],
    options_note: `Opt ${x}`,
    options: { enum: [{ raw: 0, label: `Lab ${x}` }], enum_source: `Src ${x}`, bounds_note: `Bounds ${x}` },
    provenance: { registry_record: `rec ${x}`, firmware_evidence: `fw ${x}`, ha_evidence: `ha ${x}` },
  };
}

describe("escaping", () => {
  it("esc() escapes the five HTML-significant characters and stringifies safely", () => {
    assert.equal(esc(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
    assert.equal(esc(null), "");
    assert.equal(esc(undefined), "");
    assert.equal(esc(245), "245");
  });

  it("hostile registry text and hostile entity states cannot inject markup", () => {
    const it = hostileItem();
    const v = resolveValue(it, withEntity(mockStates(), entityOf("battery_control_mode"), fresh('<script>alert("x")</script>')), CATALOGUE, CFG, NOW);
    const html = renderItem(it, v, true);
    assert.ok(!/<img|<script/i.test(html), html.slice(0, 400));
    assert.ok(html.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"));
    assert.ok(html.includes("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"));
    // the hostile id stays inside its quoted attributes
    assert.ok(html.includes('data-id="evil&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"'));
  });

  it("a hostile title and footer are escaped in the shell", () => {
    const html = renderShell('<b onclick="x()">T</b>', "", CATALOGUE, '<i onclick="y()">F</i>');
    assert.ok(!html.includes("<b onclick") && !html.includes("<i onclick"));
  });
});

describe("item rows and technical details", () => {
  const values = allValues();

  it("every item renders every requested field in its expanded details", () => {
    const labels = [
      "Current value",
      "Register",
      "Raw value",
      "Decoded value",
      "Status",
      "Why it is not writable here",
      "Evidence",
      "Danger",
      "Available options",
      "Explanation",
      "Source entity",
      "Provenance",
    ];
    for (const it of CATALOGUE.items) {
      const html = renderItemDetails(it, values.get(it.id)!);
      for (const l of labels) assert.ok(html.includes(`<dt>${l}</dt>`), `${it.id}: ${l}`);
      assert.ok(html.includes(esc(it.provenance.registry_record)), it.id);
      assert.ok(html.includes(esc(it.lock_reason)), it.id);
    }
  });

  it("a row is one toggle button with aria-expanded and aria-controls; details only when expanded", () => {
    const it = item("export_limit");
    const v = values.get("export_limit")!;
    const closed = renderItem(it, v, false);
    assert.match(closed, /<button type="button" class="row" data-action="toggle-item" data-id="export_limit" aria-expanded="false" aria-controls="d-export_limit">/);
    assert.ok(!closed.includes('id="d-export_limit"'));
    const open = renderItem(it, v, true);
    assert.ok(open.includes('aria-expanded="true"'));
    assert.ok(open.includes('id="d-export_limit"'));
    assert.ok(open.includes(`${GP_MOCK_W} W`));
    assert.ok(open.includes("reg 245"));
  });

  it("unknown values render as words, never as 0", () => {
    for (const st of ["unavailable", "unknown"]) {
      const v = resolveValue(item("export_limit"), withEntity(mockStates(), entityOf("export_limit"), fresh(st)), CATALOGUE, CFG, NOW);
      const html = renderItem(item("export_limit"), v, true);
      assert.ok(html.includes(`<span class="val v-${st}">${st === "unknown" ? "Unknown" : "Unavailable"}</span>`));
      assert.ok(!/>0( W)?</.test(html));
      assert.ok(html.includes("No live value"));
    }
    const unmapped = resolveValue(item("inverter_rated_power"), {}, CATALOGUE, CFG, NOW);
    const row = renderItem(item("inverter_rated_power"), unmapped, true);
    assert.ok(row.includes("Not exposed by an ECCO entity"));
    assert.ok(row.includes('<span class="reg">no register</span>'));
  });

  it("raw values read as one phrase: hex, decimal, reported / derived, how", () => {
    const states = mockStates();
    const html = renderResults(groupBySection(CATALOGUE, CATALOGUE.items), allValues(states), new Set(CATALOGUE.items.map((i) => i.id)));
    assert.ok(!/derived: derived|reported: reported|derived derived|reported reported/.test(html));
    const raws = [...html.matchAll(/<dt>Raw value<\/dt><dd>([^<]*)<\/dd>/g)].map((m) => m[1] ?? "");
    assert.equal(raws.length, CATALOGUE.items.length);
    for (const r of raws) assert.match(r, /^(0x[0-9A-F]{4} \(-?\d+\), (derived|reported) \S.*|Not available: \S.*)$/, r);
  });

  it("stale and unverified values are labelled as such", () => {
    const old: HassEntityLike = { state: "100", attributes: { unit_of_measurement: "W" }, last_reported: iso(3_600_000) };
    const s = withEntity(mockStates(), entityOf("export_limit"), old);
    s[entityId(CATALOGUE.freshness_gates.configuration, PREFIX)] = fresh("off");
    const v = resolveValue(item("export_limit"), s, CATALOGUE, CFG, NOW);
    assert.ok(renderItem(item("export_limit"), v, false).includes('class="fresh f-stale"'));
    const v2 = resolveValue(item("export_limit"), withEntity(s, entityOf("export_limit"), { state: "100" }), CATALOGUE, CFG, NOW);
    assert.ok(renderItem(item("export_limit"), v2, false).includes("Freshness not verified"));
  });

  it("an empty result says so", () => {
    assert.equal(renderResults(groupBySection(CATALOGUE, []), new Map(), new Set()), `<p class="empty">No setting matches the search and filters.</p>`);
  });

  it("only sections with matches are shown, each heading carrying its count", () => {
    const f = emptyFilter();
    f.query = "245";
    const hits = filterItems(CATALOGUE, f);
    const html = renderResults(groupBySection(CATALOGUE, hits), values, new Set());
    const shown = [...html.matchAll(/<h3>([^<]+) <span class="count">(\d+)<\/span><\/h3>/g)].map((m) => [m[1], Number(m[2])]);
    const expected = CATALOGUE.sections
      .map((s) => [esc(s.title), hits.filter((i) => i.section === s.id).length] as const)
      .filter(([, n]) => n > 0);
    assert.deepEqual(shown, expected);
    const inverterPower = CATALOGUE.sections.find((s) => s.id === "inverter_power")!;
    assert.ok(html.includes(`<h3>${esc(inverterPower.title)} <span class="count">1</span></h3>`));
  });
});

describe("filters and summary", () => {
  it("renders status, evidence and category chips with aria-pressed", () => {
    const f = emptyFilter();
    const html = renderFilters(CATALOGUE, f);
    const chips = [...html.matchAll(/data-action="toggle-filter" data-kind="(\w+)" data-value="([^"]+)" aria-pressed="(true|false)"/g)];
    const kinds = chips.map((m) => m[1]);
    assert.equal(kinds.filter((k) => k === "status").length, 5);
    assert.equal(kinds.filter((k) => k === "section").length, CATALOGUE.sections.length);
    const presentEvidence = new Set(CATALOGUE.items.map((i) => i.evidence));
    assert.equal(kinds.filter((k) => k === "evidence").length, presentEvidence.size);
    assert.ok(chips.every((m) => m[3] === "false"));
    assert.ok(!html.includes("clear-filters"));
    f.statuses.add("LOCKED");
    const html2 = renderFilters(CATALOGUE, f);
    assert.ok(html2.includes('data-value="LOCKED" aria-pressed="true"'));
    assert.ok(html2.includes('data-action="clear-filters"'));
    const g = emptyFilter();
    g.query = "x";
    assert.ok(renderFilters(CATALOGUE, g).includes('data-action="clear-filters"'));
  });

  it("the summary states the counts and that the page is read-only", () => {
    assert.equal(renderSummary(1, 165), "1 of 165 settings shown. This page is read-only.");
  });
});

describe("Global Power panel", () => {
  const states = mockStates();
  const html = renderGlobalPower(buildGlobalPowerView(CATALOGUE, states, CFG, NOW));

  it("identifies register 245 and shows value, raw value, unit, freshness, source and evidence", () => {
    assert.ok(html.includes("<h2>Global Power / Export Limit</h2>"));
    assert.ok(html.includes('<span class="gp-reg">Register 245</span>'));
    assert.ok(html.includes('<span class="badge ro">READ ONLY</span>'));
    assert.ok(html.includes(`<span class="big v-ok">${GP_MOCK_W} W</span>`));
    assert.ok(html.includes("<dt>Raw value</dt><dd>0x0DAC (3500), derived from the value</dd>"));
    assert.ok(html.includes("<dt>Unit</dt><dd>W</dd>"));
    assert.ok(html.includes("<dt>Read freshness</dt><dd>Live"));
    assert.ok(html.includes("<code>sensor.ecco_clock_dongle_ecco_export_limit</code>"));
    assert.ok(html.includes("M2 read-proven (registry: live_proven_read)"));
    assert.ok(html.includes("<dt>Hardware maximum</dt><dd>Hardware maximum not verified</dd>"));
    assert.ok(html.includes("Regulatory export allowance not recorded"));
  });

  it("shows the future controls, all disabled, with no action attribute anywhere in the panel", () => {
    for (const label of ["Unlock", "Staged value", "Permitted technical range", "Apply", "Verification status", "Previous value", "History"]) {
      assert.ok(html.includes(label), label);
    }
    assert.deepEqual(actions(html), []);
    const buttons = [...html.matchAll(/<button[^>]*>/g)].map((m) => m[0]);
    assert.equal(buttons.length, 2);
    for (const b of buttons) {
      assert.match(b, / disabled aria-disabled="true"/);
      assert.ok(!b.includes("data-action"));
      assert.match(b, /type="button"/);
    }
    const inputs = [...html.matchAll(/<input[^>]*>/g)].map((m) => m[0]);
    assert.equal(inputs.length, 1);
    assert.match(inputs[0] ?? "", / disabled aria-disabled="true"/);
    assert.ok(html.includes("Design preview: these controls are disabled."));
  });

  it("never shows an 8000 W (or any) hardware maximum by default", () => {
    assert.ok(!html.includes("8000"));
    assert.ok(html.includes("Unavailable: hardware maximum not verified"));
  });

  it("an unknown or missing Global Power value is a word, never 0 W", () => {
    const unknown = renderGlobalPower(buildGlobalPowerView(CATALOGUE, withEntity(states, entityOf("export_limit"), fresh("unknown")), CFG, NOW));
    assert.ok(unknown.includes('<span class="big v-unknown">Unknown</span>'));
    assert.ok(!unknown.includes(">0 W<"));
    const missing = renderGlobalPower(buildGlobalPowerView(CATALOGUE, {}, CFG, NOW));
    assert.ok(missing.includes("Entity not found in Home Assistant"));
    assert.ok(missing.includes("No live value"));
  });
});

describe("the whole rendered card", () => {
  const html = wholeCard();

  it("carries only the four local view actions", () => {
    const found = new Set(actions(html));
    for (const a of found) assert.ok(ALLOWED_ACTIONS.has(a), a);
    assert.deepEqual([...found].sort(), [...ALLOWED_ACTIONS].sort());
  });

  it("has no form, link, frame, script or inline event handler", () => {
    assert.ok(!/<form|<a\s|<iframe|<script|<object|<embed/i.test(html));
    assert.ok(!/\son[a-z]+=/i.test(html.replace(/&quot;|&#39;/g, "")));
  });

  it("every button is type=button (nothing can submit)", () => {
    const buttons = [...html.matchAll(/<button[^>]*>/g)].map((m) => m[0]);
    assert.ok(buttons.length > 165);
    for (const b of buttons) assert.match(b, /type="button"/);
  });

  it("the search box is labelled, bounded and does not autocomplete", () => {
    assert.match(html, /<input type="search" data-action="search" placeholder="[^"]+" autocomplete="off" spellcheck="false" maxlength="200">/);
    for (const r of ["gp", "filters", "summary", "results"]) assert.ok(html.includes(`data-region="${r}"`), r);
  });
});

describe("mobile / responsive styles", () => {
  it("is single-column by default with a wider layout from the breakpoint", () => {
    assert.equal(MOBILE_BREAKPOINT_PX, 700);
    assert.ok(STYLES.includes("@media (min-width:700px)"));
    assert.ok(STYLES.includes("@media (max-width:699px)"));
    assert.match(STYLES, /\.kv\{display:grid;grid-template-columns:1fr;/);
    assert.match(STYLES, /\.ctl-grid\{display:grid;grid-template-columns:1fr;/);
  });

  it("gives every interactive control a 44px touch target", () => {
    assert.equal(TOUCH_TARGET_PX, 44);
    for (const sel of [".chip{", ".row{", ".search input{", ".link{", ".ctl-btn,.ctl-in{", ".gp-why summary{"]) {
      const rule = STYLES.slice(STYLES.indexOf(sel), STYLES.indexOf("}", STYLES.indexOf(sel)));
      assert.ok(STYLES.includes(sel), sel);
      assert.match(rule, /min-height:44px/, sel);
    }
  });

  it("never forces a width wider than a phone and wraps long register text", () => {
    assert.ok(!/(?:^|[;{])\s*(?:min-)?width:\s*(?:[4-9]\d{2}|\d{4,})px/.test(STYLES));
    assert.ok(STYLES.includes("overflow-wrap:anywhere"));
    assert.ok(STYLES.includes("box-sizing:border-box"));
  });

  it("does not rely on colour alone for pressed filters or locked settings", () => {
    assert.ok(STYLES.includes('.chip[aria-pressed="true"]::before'));
    assert.ok(STYLES.includes(".tag.t-LOCKED,.tag.t-UNSUPPORTED{font-weight:600}"));
  });
});
