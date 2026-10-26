// Safety: the card is read-only and self-contained. It calls no Home
// Assistant service, opens no socket, writes nothing, and loads nothing from
// the network.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const card = fileURLToPath(new URL("..", import.meta.url));

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) sources(p, out);
    else if (name.endsWith(".ts")) out.push(p);
  }
  return out;
}

const srcFiles = sources(join(card, "src"));
const src = srcFiles.map((p) => readFileSync(p, "utf-8")).join("\n");

test("no service calls, websocket calls or API writes anywhere in the source", () => {
  for (const forbidden of ["callService", "callWS", "callApi", "sendMessagePromise", "fetch(", "XMLHttpRequest", "WebSocket", "navigator.sendBeacon", "localStorage", "sessionStorage", "indexedDB"]) {
    assert.ok(!src.includes(forbidden), `source must not contain ${forbidden}`);
  }
});

test("the only event the card emits is Home Assistant's own more-info request", () => {
  const events = [...src.matchAll(/new CustomEvent\("([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual([...new Set(events)], ["hass-more-info"]);
  assert.ok(!/dispatchEvent\((?!new CustomEvent\("hass-more-info")/.test(src));
});

test("no external resource: no http(s) URL, no image, font or CDN reference in the source or the bundle", () => {
  for (const [name, text] of [["source", src], ["bundle", readFileSync(join(card, "dist", "ecco-flow-3d-card.js"), "utf-8")]] as const) {
    const urls = (text.match(/https?:\/\/[^\s"'`)]+/g) ?? []).filter((u) => !/^https?:\/\/(lit\.dev|github\.com|opensource\.org|www\.w3\.org|polymer\.github\.io|developer\.mozilla\.org|developers\.google\.com)\b/.test(u));
    assert.deepEqual(urls, [], `${name} contains network URLs beyond licence/spec references`);
    assert.doesNotMatch(text, /<img\b|@import\s+url|url\(\s*["']?https?:/i, `${name} loads nothing external`);
    assert.doesNotMatch(text, /\bimport\(\s*["'`]https?:/, `${name} has no dynamic network import`);
  }
});

test("the configuration schema has no action, service or write fields", () => {
  const config = readFileSync(join(card, "src", "config.ts"), "utf-8");
  // Property keys only (comments may mention the words while saying the card never does them).
  const keys = [...config.matchAll(/^\s+([a-z_]+)\??:/gm)].map((m) => m[1]!);
  const forbidden = keys.filter((k) => /^(tap_action|hold_action|double_tap_action|service|action|actions|write|call|set)(_|$)/.test(k));
  assert.deepEqual(forbidden, []);
});

test("no value is fabricated: the card never renders a plausible number for an unknown reading", () => {
  // Every formatter returns "--" for an unknown value.
  for (const fn of ["formatPower", "formatPowerCompact", "formatEnergy", "formatPercent", "formatDurationMinutes", "formatApproxMinutes"]) {
    const re = new RegExp(`export function ${fn}[^{]*\\{[\\s\\S]*?return "--";`);
    assert.match(src, re, `${fn} returns "--" for unknown`);
  }
  // No entity reading is defaulted to 0: `numberOf(...)` / `toNumber(...)` results are never followed by `?? 0`.
  assert.doesNotMatch(src, /(numberOf|toNumber)\([^)]*\)\s*\?\?\s*0\b/);
  // The only `?? 0` defaults are a precision and an array length, not readings.
  const zeroDefaults = [...src.matchAll(/[^\n]*\?\?\s*0\b[^\n]*/g)].map((m) => m[0].trim());
  assert.deepEqual(zeroDefaults, ["return `${watts.toFixed(format?.precision ?? 0)} W`;", "(ecco.health?.sensors?.length ?? 0) > 0"]);
});

test("the bundle registers the card's own tag and no other card's", () => {
  const bundle = readFileSync(join(card, "dist", "ecco-flow-3d-card.js"), "utf-8");
  assert.ok(bundle.includes('"ecco-flow-3d-card"'), "custom element tag present");
  assert.ok(bundle.includes('type:"ecco-flow-3d-card"'), "card-picker registration present");
  const otherTags = [...bundle.matchAll(/"(ecco-[a-z0-9-]+-card)"/g)].map((m) => m[1]).filter((t) => t !== "ecco-flow-3d-card");
  assert.deepEqual([...new Set(otherTags)], [], "no other ECCO card tag is registered or referenced");
});
