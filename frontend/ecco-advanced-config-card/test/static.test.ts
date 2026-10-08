// Static proof of the read-only guarantee over the card's source and its built bundle: no Home Assistant service,
// websocket or API call, no network, no storage, no dynamic code, and only the four local view actions.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const CARD = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(CARD, "src");
const read = (p: string): string => readFileSync(p, "utf8");
const sources = readdirSync(SRC)
  .filter((f) => f.endsWith(".ts"))
  .sort()
  .map((f) => ({ name: `src/${f}`, text: read(join(SRC, f)) }));
const code = sources.filter((s) => s.name !== "src/catalogue.generated.ts");
const dist = read(join(CARD, "dist", "ecco-advanced-config-card.js"));

// Identifiers / calls that would give a Lovelace card a way to change anything outside its own shadow DOM.
const FORBIDDEN = [
  "callService",
  "callWS",
  "callApi",
  "fetchWithAuth",
  "sendMessage",
  "subscribeMessage",
  "subscribeEvents",
  "perform_action",
  "XMLHttpRequest",
  "WebSocket",
  "EventSource",
  "sendBeacon",
  "importScripts",
  "localStorage",
  "sessionStorage",
  "indexedDB",
  "postMessage",
  "document.cookie",
  "hass-action",
  "hass-more-info",
  "ll-custom",
  "dispatchEvent",
  "button.press",
  "switch.turn_on",
  "switch.turn_off",
  "number.set_value",
  "select.select_option",
  "input_number.set_value",
];
const FORBIDDEN_RE = [/\bfetch\s*\(/, /\beval\s*\(/, /\bnew\s+Function\s*\(/, /\bimport\s*\(/, /\bsetInterval\s*\(/, /\bsetTimeout\s*\(/];

describe("no write authority in the source", () => {
  it("names no service, websocket, network, storage or event-dispatch API (code and generated catalogue)", () => {
    for (const s of sources) {
      for (const tok of FORBIDDEN) assert.ok(!s.text.includes(tok), `${s.name}: ${tok}`);
    }
    for (const s of code) {
      for (const re of FORBIDDEN_RE) assert.ok(!re.test(s.text), `${s.name}: ${re}`);
    }
  });

  it("reads only the states map of the Home Assistant object and never stores the object", () => {
    const card = read(join(SRC, "ecco-advanced-config-card.ts"));
    const uses = [...card.matchAll(/\bhass\b[^\n]*/g)].map((m) => m[0]);
    assert.ok(uses.length > 0);
    assert.ok(!/this\.(?:_?hass)\b\s*=/.test(card), "the hass object is never assigned to the card");
    assert.ok(!/\bhass\s*\.\s*(?!states\b)[A-Za-z_]/.test(card.replace(/\(hass as \{ states\?: unknown \}\)\.states/g, "")), uses.join("\n"));
    assert.equal((card.match(/set hass\(/g) ?? []).length, 1);
    assert.ok(!/get hass\(/.test(card));
  });

  it("listens only for input and click, and handles only the four local view actions", () => {
    const all = code.map((s) => s.text).join("\n");
    const listeners = [...all.matchAll(/addEventListener\(\s*"([a-z]+)"/g)].map((m) => m[1]);
    assert.deepEqual(listeners.sort(), ["click", "input"]);
    const emitted = new Set([...all.matchAll(/data-action="([a-z-]+)"/g)].map((m) => m[1]));
    assert.deepEqual([...emitted].sort(), ["clear-filters", "search", "toggle-filter", "toggle-item"]);
    const handled = new Set([...all.matchAll(/(?:action|getAttribute\("data-action"\)) (?:===|!==) "([a-z-]+)"/g)].map((m) => m[1]));
    assert.deepEqual([...handled].sort(), ["clear-filters", "search", "toggle-filter", "toggle-item"]);
  });

  it("renders the Global Power write controls disabled and without an action", () => {
    const render = read(join(SRC, "render.ts"));
    const gp = render.slice(render.indexOf("export function renderGlobalPower"), render.indexOf("export function renderShell"));
    assert.ok(gp.length > 500);
    assert.ok(!gp.includes("data-action"));
    assert.equal((gp.match(/<button /g) ?? []).length, 1, "one button template (Unlock / Apply)");
    assert.equal((gp.match(/<input /g) ?? []).length, 1, "one input template (Staged value)");
    for (const tag of gp.match(/<(?:button|input) [^>]*>/g) ?? []) assert.match(tag, / disabled aria-disabled="true"/);
  });

  it("never assumes an 8000 W hardware maximum in code", () => {
    for (const s of code) assert.ok(!/\b8000\b/.test(s.text), s.name);
  });
});

describe("no write authority in the built bundle", () => {
  it("names no service, websocket, network, storage or event-dispatch API", () => {
    for (const tok of FORBIDDEN) assert.ok(!dist.includes(tok), tok);
    for (const re of [/\bfetch\s*\(/, /\beval\s*\(/, /\bnew Function\s*\(/, /\bimport\s*\(/, /\bsetInterval\s*\(/, /\bsetTimeout\s*\(/]) {
      assert.ok(!re.test(dist), String(re));
    }
  });

  it("is self-contained: no import, no require, no source map, no local path", () => {
    assert.ok(!/(?:^|[;\n])\s*import\s*[\s{*"']/.test(dist));
    assert.ok(!/\brequire\s*\(/.test(dist));
    assert.ok(!dist.includes("sourceMappingURL"));
    assert.ok(!/[A-Za-z]:\\|\/Users\/|\/home\/|node_modules/.test(dist));
  });

  it("listens only for input and click", () => {
    const listeners = [...dist.matchAll(/addEventListener\("([a-z]+)"/g)].map((m) => m[1]);
    assert.deepEqual([...new Set(listeners)].sort(), ["click", "input"]);
  });
});
