// Static proof of the read-only guarantee over the card's source and its built bundle. Unlike the Advanced Configuration
// card (states only), this card needs Home Assistant's websocket for the weather forecast and hourly PV statistics, so the
// guarantee is an ALLOWLIST: exactly two read-only message types, sent only from src/reader.ts; no service / action call,
// no event subscription, no network, no storage, no timer, no dynamic code; one local view action.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const CARD = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(CARD, "src");
const read = (p: string): string => readFileSync(p, "utf8");
const sources = readdirSync(SRC).filter((f) => f.endsWith(".ts")).sort().map((f) => ({ name: `src/${f}`, text: read(join(SRC, f)) }));
const dist = read(join(CARD, "dist", "ecco-weather-solar-card.js"));
/** Code only: comments removed (they may name the messages they describe). */
const code = (text: string): string => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
const ALLOWED_MESSAGES = ["weather/subscribe_forecast", "recorder/statistics_during_period"];

// Anything that would let a Lovelace card change something outside its own shadow DOM, or reach beyond the two messages.
const FORBIDDEN = [
  "callService", "callWS", "callApi", "fetchWithAuth", "subscribeEvents", "perform_action", "return_response",
  "call_service", "execute_script", "fire_event", "subscribe_events", "subscribe_trigger", "render_template",
  "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "importScripts", "localStorage", "sessionStorage", "indexedDB",
  "postMessage", "document.cookie", "hass-action", "hass-more-info", "ll-custom", "dispatchEvent", "location-changed",
  "button.press", "switch.turn_on", "switch.turn_off", "number.set_value", "select.select_option", "input_number.set_value",
  "modbus", "esphome.",
];
const FORBIDDEN_RE = [/\bfetch\s*\(/, /\beval\s*\(/, /\bnew\s+Function\s*\(/, /\bimport\s*\(/, /\bsetInterval\s*\(/, /\bsetTimeout\s*\(/,
  /\brequestAnimationFrame\s*\(/, /\bsendMessage\b(?!Promise)/];
const WS_PREFIXES = /["'`](?:auth|config|lovelace|energy|history|logbook|recorder|weather|frontend|search|repairs|backup|person|template|automation|script|system_log|hassio|supervisor)\/[a-z_/]+["'`]/g;

describe("the source", () => {
  it("names no service, action, event, network, storage, timer or dynamic-code API", () => {
    for (const s of sources) {
      for (const tok of FORBIDDEN) assert.ok(!s.text.includes(tok), `${s.name}: ${tok}`);
      for (const re of FORBIDDEN_RE) assert.ok(!re.test(s.text), `${s.name}: ${re}`);
    }
  });

  it("only src/reader.ts touches the connection, and it sends exactly the two allowed message types", () => {
    for (const s of sources) {
      const touches = /\bsubscribeMessage\b|\bsendMessagePromise\b/.test(code(s.text));
      assert.equal(touches, s.name === "src/reader.ts", s.name);
      const types = [...code(s.text).matchAll(WS_PREFIXES)].map((m) => m[0].slice(1, -1));
      assert.deepEqual([...new Set(types)].sort(), s.name === "src/reader.ts" ? [...ALLOWED_MESSAGES].sort() : [], `${s.name}: ${types.join(", ")}`);
    }
    const reader = read(join(SRC, "reader.ts"));
    assert.equal((reader.match(/conn\.subscribeMessage\(/g) ?? []).length, 1);
    assert.equal((reader.match(/conn\.sendMessagePromise\(/g) ?? []).length, 1);
    assert.equal((reader.match(/\btype: WS_FORECAST\b/g) ?? []).length, 1);
    assert.equal((reader.match(/\btype: WS_STATISTICS\b/g) ?? []).length, 1);
    assert.equal((reader.match(/\btype:/g) ?? []).length, 2, "no other message object");
  });

  it("the card reads only states, config and connection from the hass object, and keeps none of them as such", () => {
    const card = read(join(SRC, "ecco-weather-solar-card.ts"));
    assert.equal((card.match(/set hass\(/g) ?? []).length, 1);
    assert.ok(!/get hass\(/.test(card));
    assert.ok(!/this\.(?:_?hass|_?connection|_?conn)\s*=/.test(card), "the hass object / connection are never assigned to the card");
    const props = [...card.matchAll(/\bh\.([A-Za-z_]+)/g)].map((m) => m[1]);
    assert.deepEqual([...new Set(props)].sort(), ["config", "connection", "states"]);
  });

  it("listens only for click and handles only the chart-day view action", () => {
    const all = sources.map((s) => s.text).join("\n");
    assert.deepEqual([...all.matchAll(/addEventListener\(\s*"([a-z]+)"/g)].map((m) => m[1]), ["click"]);
    assert.deepEqual([...new Set([...all.matchAll(/data-action="([a-z-]+)"/g)].map((m) => m[1]))], ["chart-day"]);
    assert.deepEqual([...new Set([...all.matchAll(/getAttribute\("data-action"\) === "([a-z-]+)"/g)].map((m) => m[1]))], ["chart-day"]);
  });

  it("does not recompute or re-weight the ECCO blend: the displayed blend is the blend sensor's own state", () => {
    const all = sources.map((s) => code(s.text)).join("\n");
    const averages = [...all.matchAll(/\(\s*[\w.]*solcast[\w.]*\s*\+\s*[\w.]*forecastSolar[\w.]*\s*\)\s*\/\s*2|\b0\.5\s*\*\s*[\w.]*(?:solcast|forecastSolar)/gi)].map((m) => m[0]);
    assert.deepEqual(averages, ["(t.solcast + t.forecastSolar) / 2"], "the only mean is the disagreement threshold of an insight note");
    const model = code(read(join(SRC, "model.ts")));
    assert.ok(/const blend = b \? toNum\(b\.state\) : null;/.test(model), "solarTotals reads the blend sensor's state");
    for (const f of ["model.ts", "reader.ts", "ecco-weather-solar-card.ts"]) {
      assert.ok(!/weight/i.test(code(read(join(SRC, f)))), `no weighting in the logic of ${f}`);
    }
  });
});

describe("the built bundle", () => {
  it("names no forbidden API and contains exactly the two allowed message types", () => {
    for (const tok of FORBIDDEN) assert.ok(!dist.includes(tok), tok);
    for (const re of FORBIDDEN_RE) assert.ok(!re.test(dist), String(re));
    const types = [...dist.matchAll(WS_PREFIXES)].map((m) => m[0].slice(1, -1));
    assert.deepEqual([...new Set(types)].sort(), [...ALLOWED_MESSAGES].sort());
  });

  it("is self-contained: no import, no require, no source map, no local path", () => {
    assert.ok(!/(?:^|[;\n])\s*import\s*[\s{*"']/.test(dist));
    assert.ok(!/\brequire\s*\(/.test(dist));
    assert.ok(!dist.includes("sourceMappingURL"));
    assert.ok(!/[A-Za-z]:\\|\/Users\/|\/home\/|node_modules/.test(dist));
  });

  it("listens only for click", () => {
    assert.deepEqual([...new Set([...dist.matchAll(/addEventListener\("([a-z]+)"/g)].map((m) => m[1]))], ["click"]);
  });
});
