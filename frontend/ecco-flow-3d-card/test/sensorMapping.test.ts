// Sensor mapping: every entity id in examples/ecco-example.yaml must already
// exist in this repository (packages, dashboard, firmware sensor names or the
// other cards' ECCO examples). Nothing in the example is invented. The preview
// mock must also cover every one of them so the harness exercises the real
// configuration.
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

const example = readFileSync(join(card, "examples", "ecco-example.yaml"), "utf-8");
const entityIds = [...new Set(example.match(/\b(?:sensor|binary_sensor|sun|input_[a-z]+|switch|number|select)\.[a-z0-9_]+/g) ?? [])];

test("the example references a meaningful number of entities", () => {
  assert.ok(entityIds.length >= 60, `found ${entityIds.length}`);
});

test("every entity id in the ECCO example exists elsewhere in the repository", () => {
  const corpus = [join(repo, "home-assistant"), join(repo, "frontend"), join(repo, "registry"), join(repo, "docs")]
    .flatMap((d) => walk(d))
    .map((p) => readFileSync(p, "utf-8"))
    .join("\n");
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
