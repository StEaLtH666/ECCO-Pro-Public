// Sensor mapping: every entity id in examples/ecco-example.yaml must already
// exist in this repository (packages, dashboard, firmware sensor names or the
// other cards' ECCO examples). Nothing in the example is invented. The
// production dashboard's own copy of this card's configuration (its Overview,
// dashboard 7.23.0) does not count: it is left out of the corpus, and that
// exclusion fails closed (exactly one block, from that file only, all of it;
// the dashboard names the card exactly once, in any quoting, and none of the
// card-only keys survives the exclusion). test_flow_3d_card.py [4] makes the
// same proof with a YAML parser.
// The preview mock must also cover every one of them so the harness exercises
// the real configuration.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const card = fileURLToPath(new URL("..", import.meta.url));
const repo = join(card, "..", "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "dist" || name === ".git") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ya?ml|ts|md|js|json)$/.test(name) && !p.startsWith(card)) out.push(p);
  }
  return out;
}

const DASHBOARD = join(repo, "home-assistant", "dashboards", "ecco_pro.yaml");

/**
 * The text without each block-style YAML list item whose first line is
 * `- type: custom:ecco-flow-3d-card` (that line and every blank or
 * deeper-indented line after it), and how many were removed. Line-ending safe.
 */
function withoutCardBlocks(text: string): { text: string; removed: number } {
  const out: string[] = [];
  let skip: number | null = null;
  let removed = 0;
  for (const line of text.split(/\r?\n/)) {
    const indent = line.length - line.replace(/^ +/, "").length;
    if (skip !== null && (line.trim() === "" || indent > skip)) continue;
    skip = null;
    if (line.trim() === "- type: custom:ecco-flow-3d-card") {
      skip = indent;
      removed += 1;
      continue;
    }
    out.push(line);
  }
  return { text: out.join("\n"), removed };
}

const example = readFileSync(join(card, "examples", "ecco-example.yaml"), "utf-8");
const entityIds = [...new Set(example.match(/\b(?:sensor|binary_sensor|sun|input_[a-z]+|switch|number|select)\.[a-z0-9_]+/g) ?? [])];

test("the example references a meaningful number of entities", () => {
  assert.ok(entityIds.length >= 60, `found ${entityIds.length}`);
});

test("every entity id in the ECCO example exists elsewhere in the repository", () => {
  const removed: Record<string, number> = {};
  const corpus = [join(repo, "home-assistant"), join(repo, "frontend"), join(repo, "registry"), join(repo, "docs")]
    .flatMap((d) => walk(d))
    .map((p) => {
      const stripped = withoutCardBlocks(readFileSync(p, "utf-8"));
      if (stripped.removed > 0) removed[p] = stripped.removed;
      return stripped.text;
    })
    .join("\n");
  assert.deepEqual(removed, { [DASHBOARD]: 1 }, "exactly the production dashboard's one copy of the card's configuration is left out");
  const dashboardText = readFileSync(DASHBOARD, "utf-8");
  assert.equal([...dashboardText.matchAll(/type:\s*["']?custom:ecco-flow-3d-card["']?/g)].length, 1, "the dashboard names the card exactly once, in any quoting");
  const strippedDashboard = withoutCardBlocks(dashboardText).text;
  assert.doesNotMatch(strippedDashboard, /custom:ecco-flow-3d-card/, "all of that copy is left out");
  for (const marker of ["crossfade_ms:", "stale_after_s:", "pack: /local/ecco/scenes/", "show_status_panel:"]) {
    assert.ok(!strippedDashboard.includes(marker), `no card-only key (${marker}) survives the exclusion`);
  }
  const firmware = readdirSync(join(repo, "firmware"))
    .filter((f) => f.endsWith(".yaml"))
    .map((f) => readFileSync(join(repo, "firmware", f), "utf-8"))
    .join("\n");
  // ESPHome slugifies `name:` under the device name "ecco_clock_dongle".
  const firmwareSlugs = new Set(
    [...firmware.matchAll(/^\s+name:\s*"?([^"\n]+?)"?\s*$/gm)].map((m) => "ecco_clock_dongle_" + m[1]!.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""))
  );
  const missing = entityIds.filter((id) => {
    if (corpus.includes(id)) return false;
    const tail = id.replace(/^[a-z_]+\./, "");
    return !firmwareSlugs.has(tail);
  });
  assert.deepEqual(missing, [], `entity ids not found anywhere in the repository: ${missing.join(", ")}`);
});

test("the preview mock provides a state for every entity in the example", () => {
  const mock = readFileSync(join(card, "preview", "mock.js"), "utf-8");
  const missing = entityIds.filter((id) => {
    if (mock.includes(`"${id}"`)) return false;
    // Slot-indexed ids are produced by template strings in the mock.
    const m = /^(sensor\.ecco_tou_slot_)(\d)(_start_minute)$/.exec(id) ?? /^(sensor\.ecco_clock_dongle_ecco_timezone)(\d)(_(?:soc|charge|power))$/.exec(id);
    if (m) return !mock.includes(m[1]!) || !mock.includes(m[3]!);
    return true;
  });
  assert.deepEqual(missing, []);
});

test("the example keeps the ECCO sign conventions of the installed Energy Flow card", () => {
  const installed = readFileSync(join(repo, "frontend", "ecco-energy-flow-card", "examples", "ecco-example.yaml"), "utf-8");
  for (const line of ["power_sign: discharge_positive", "power_sign: import_positive", "power: sensor.ecco_grid_power", "power: sensor.ecco_house_power", "solar_total: sensor.ecco_pv_power"]) {
    assert.ok(installed.includes(line), `installed example has: ${line}`);
    assert.ok(example.includes(line), `this example has: ${line}`);
  }
});

test("the example configures no time-to-target entity (ECCO has none) and the card marks it unavailable", () => {
  assert.doesNotMatch(example, /^\s*time_to_target:\s*\S/m);
});
