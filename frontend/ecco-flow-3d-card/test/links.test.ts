// Card links on the artwork plates (scene.links): which style renders, which links and card borders breathe, and
// how a configured value is read. The scene is rendered to its Lit template and flattened to markup text. The three
// rendering tests need Lit (npm ci); where it is not installed (CI installs no npm package) they are reported as skipped,
// never as passed, as the rebuild tests in build.test.ts are. The other tests need no package and always run.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { FlowView, PillData, SceneModel } from "../src/scene/scene.ts";
import { V4_LAYOUT } from "../src/scene/iso.ts";
import { buildFlowEdges, splitSolarFlows, type FlowId } from "../src/core/power.ts";
import { BORDER_ACTIVE_MIN, BORDER_IDLE_OPACITY, LINK_ACTIVE_MIN, LINK_IDLE_OPACITY, motionFor } from "../src/core/motion.ts";
import { linkStyleOf, validateConfig, type LinkStyle } from "../src/config.ts";

// Only the absence of Lit is tolerated: once Lit is present the scene module is imported unguarded, so any other failure
// to load it still fails this file.
let hasLit = true;
try {
  await import("lit");
} catch {
  hasLit = false;
}
const renderScene: ((m: SceneModel) => unknown) | null = hasLit ? (await import("../src/scene/scene.ts")).renderScene : null;
const needsLit = renderScene ? false : "lit is not installed (run `npm ci` in the card folder)";

/** Lit template -> markup text; attribute values are quoted so class lists can be matched. */
function flatten(v: unknown): string {
  if (v === null || v === undefined || typeof v === "symbol" || typeof v === "function" || typeof v === "boolean") return "";
  if (Array.isArray(v)) return v.map(flatten).join("");
  if (typeof v === "object" && v && "strings" in v && "values" in v) {
    const t = v as { strings: readonly string[]; values: unknown[] };
    let out = "";
    t.strings.forEach((s, i) => {
      out += s;
      if (i < t.values.length) out += s.endsWith("=") ? `"${flatten(t.values[i])}"` : flatten(t.values[i]);
    });
    return out;
  }
  return String(v);
}

interface Powers {
  pv1: number | null;
  pv2: number | null;
  total?: number | null;
  battery: number | null;
  grid: number | null;
  home: number | null;
}

const DAY: Powers = { pv1: 3350, pv2: 3050, battery: -3100, grid: -1000, home: 2300 };

function scene(p: Powers, opts: { links?: LinkStyle; stale?: boolean; animate?: boolean; arrays?: number; artwork?: boolean } = {}): string {
  const stale = !!opts.stale;
  const total = p.total !== undefined ? p.total : p.pv1 === null && p.pv2 === null ? null : (p.pv1 ?? 0) + (p.pv2 ?? 0);
  const edges = Object.fromEntries(buildFlowEdges({ solarW: total, batteryW: p.battery, gridW: p.grid, homeW: p.home }).map((e) => [e.id, e]));
  const view = (e: (typeof edges)[string]): FlowView => ({ edge: e!, motion: motionFor(e!, stale) });
  const flows = Object.fromEntries((["solar", "battery", "grid", "home"] as FlowId[]).map((id) => [id, view(edges[id])])) as Record<FlowId, FlowView>;
  const split = splitSolarFlows(total, p.pv1, p.pv2, opts.arrays ?? 2);
  const pill = (label: string, icon: PillData["icon"]): PillData => ({ label, value: "1 kW", sub: "", tone: "ok", icon, clickable: true });
  const m: SceneModel = {
    daylight: "day",
    flows,
    solarSplit: { card: view(split.card), main: view(split.main), garage: split.garage ? view(split.garage) : null },
    stale,
    animate: opts.animate ?? true,
    pills: { solar: pill("Solar", "sun"), grid: pill("Grid", "pylon"), home: pill("Home", "home"), battery: { ...pill("Battery", "battery"), soc: 50 } },
    inverterLed: "ok",
    onPill: () => {},
    artwork:
      opts.artwork === false
        ? undefined
        : { layers: [{ url: "/p/00_bright_summer_day.png", key: "bright_summer_day", entering: false }], layout: V4_LAYOUT, onError: () => {}, onLoad: () => {}, links: opts.links },
  };
  return flatten(renderScene!(m));
}

const svgClass = (html: string) => /<svg class="([^"]*)"/.exec(html)?.[1] ?? "";
const groups = (html: string, cls: string) => [...html.matchAll(/<g class="([^"]*)"/g)].map((x) => x[1]!.split(/\s+/)).filter((c) => c.includes(cls));
const pillClasses = (html: string, id: string) => groups(html, `pill-${id}`)[0] ?? [];

test("links default to the pulse style; particles and off render as before", { skip: needsLit }, () => {
  const pulse = scene(DAY);
  assert.ok(svgClass(pulse).split(" ").includes("links-pulse"));
  assert.equal(groups(pulse, "pulse-link").length, 5, "one dotted link per array, the battery, the grid and the house");
  for (const g of groups(pulse, "pulse-link")) assert.ok(g.includes("info-link"), "the pulse link is the dotted connector");
  const particles = scene(DAY, { links: "particles" });
  assert.ok(svgClass(particles).split(" ").includes("links-particles"));
  assert.equal(groups(particles, "pulse-link").length, 0);
  assert.equal(groups(particles, "info-link").length, 5);
  assert.ok(/data-path="ef3d-info-/.test(particles), "particles mode keeps its travelling particles on the links");
  assert.ok(!/data-path="ef3d-info-/.test(pulse), "pulse mode puts no moving particle on any link");
  const off = scene(DAY, { links: "off" });
  assert.ok(svgClass(off).split(" ").includes("links-off"));
  assert.equal(groups(off, "info-link").length, 0, "off draws no links");
  assert.ok(/data-path="ef3d-path-/.test(off), "the power routes keep their particles in every mode");
});

test("a link breathes exactly while its flow moves, and a card border exactly while one of its own links does", { skip: needsLit }, () => {
  const day = scene(DAY);
  for (const g of groups(day, "pulse-link")) assert.ok(g.includes("active"), `${g.join(" ")} breathes in daylight export`);
  for (const id of ["solar", "grid", "battery", "home"]) assert.ok(pillClasses(day, id).includes("breathing"), `${id} border breathes`);
  // Dawn: both arrays at 4 W (each idle) but 8 W in total, so the Solar card itself reads active.
  const dawn = scene({ pv1: 4, pv2: 4, battery: 600, grid: 0, home: 600 });
  assert.ok(pillClasses(dawn, "solar").includes("active"), "the Solar card shows its 8 W total");
  assert.ok(!pillClasses(dawn, "solar").includes("breathing"), "but its border rests while neither array link moves");
  assert.ok(!groups(dawn, "info-solar-main")[0]!.includes("active") && !groups(dawn, "info-solar-garage")[0]!.includes("active"));
  assert.ok(!pillClasses(dawn, "grid").includes("breathing") && !groups(dawn, "info-grid")[0]!.includes("active"), "an idle grid rests");
  assert.ok(pillClasses(dawn, "battery").includes("breathing"));
  // Stale telemetry: nothing breathes.
  const stale = scene(DAY, { stale: true });
  assert.ok(svgClass(stale).split(" ").includes("stale"));
  assert.equal(groups(stale, "pulse-link").filter((g) => g.includes("active")).length, 0);
  for (const id of ["solar", "grid", "battery", "home"]) assert.ok(!pillClasses(stale, id).includes("breathing"));
  // Other styles never mark a border as breathing.
  for (const links of ["particles", "off"] as const) for (const id of ["solar", "grid", "battery", "home"]) assert.ok(!pillClasses(scene(DAY, { links }), id).includes("breathing"), `${links}: ${id}`);
});

test("still mode marks the scene still; one array draws one solar link; the vector scene has no links", { skip: needsLit }, () => {
  assert.ok(svgClass(scene(DAY, { animate: false })).split(" ").includes("still"));
  const one = scene({ ...DAY, pv2: null, total: 3350 }, { arrays: 1 });
  assert.equal(groups(one, "info-solar-garage").length, 0);
  assert.equal(groups(one, "info-solar-main").length, 1);
  const vector = scene(DAY, { artwork: false });
  assert.ok(!/links-/.test(svgClass(vector)) && groups(vector, "pulse-link").length === 0);
});

test("scene.links is read leniently and checked: YAML's unquoted off is off, anything unknown is refused", () => {
  assert.equal(linkStyleOf(undefined), "pulse");
  assert.equal(linkStyleOf(true), "pulse");
  assert.equal(linkStyleOf(false), "off", "a YAML-mode dashboard turns an unquoted off into false");
  assert.equal(linkStyleOf("Off"), "off");
  assert.equal(linkStyleOf(" particles "), "particles");
  assert.equal(linkStyleOf("pulse"), "pulse");
  for (const bad of ["bogus", 42, {}, ["pulse"]]) assert.equal(linkStyleOf(bad), null);
  const base = { type: "custom:ecco-flow-3d-card", nodes: { home: { power: "sensor.h" } } };
  assert.doesNotThrow(() => validateConfig({ ...base, scene: { links: false } }));
  assert.doesNotThrow(() => validateConfig(base));
  assert.throws(() => validateConfig({ ...base, scene: { links: "pulsing" } }), /scene\.links/);
});

test("at no point of the breath does an idle link or card border outshine an active one", () => {
  // Active links also brighten their dots (opacity 1 against 0.72-0.85 idle), so comparing the group floors is the safe bound.
  assert.ok(LINK_ACTIVE_MIN >= 2 * LINK_IDLE_OPACITY, "link: the bottom of an active breath sits well above an idle link");
  assert.ok(BORDER_ACTIVE_MIN >= 2 * BORDER_IDLE_OPACITY, "border: likewise");
  assert.ok(LINK_ACTIVE_MIN <= 0.25 && BORDER_ACTIVE_MIN <= 0.5, "still a real on-and-off breath");
});
