// Static proof of the card's authority: exactly three service calls (script.turn_on on the three ACS1 scripts), made from one
// module, and nothing else that could change Home Assistant, the dongle or the inverter; no network, storage, timers or dynamic
// code; the only Home Assistant properties read are `states` and `callService`; no reserved fallback token.
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
const dist = read(join(CARD, "dist", "ecco-tou-settings-card.js"));
const all = sources.map((s) => s.text).join("\n");

// Anything that would give this card a way to change Home Assistant other than the three allowed script calls.
const FORBIDDEN = [
  "callWS", "callApi", "fetchWithAuth", "sendMessage", "subscribeMessage", "subscribeEvents", "perform_action", "call_service",
  "execute_script", "fire_event", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "importScripts", "localStorage",
  "sessionStorage", "indexedDB", "postMessage", "document.cookie", "hass-action", "hass-more-info", "ll-custom", "dispatchEvent",
  "button.press", "switch.turn_on", "switch.turn_off", "number.set_value", "select.select_option", "select.select_first",
  "input_number.set_value", "input_text.set_value", "input_boolean.turn_on", "input_boolean.turn_off", "input_select", "esphome.",
  "modbus", "script.reload", "automation.", "homeassistant.", "persistent_notification",
];
const FORBIDDEN_RE = [/\bfetch\s*\(/, /\beval\s*\(/, /\bnew\s+Function\s*\(/, /\bimport\s*\(/, /\bsetInterval\s*\(/, /\bsetTimeout\s*\(/, /\brequestAnimationFrame\s*\(/];
// The repository's reserved fallback tokens (frontend/ must not spell them; assembled so this file does not either), the B10 and
// raw-cache ids, and the FB-C3 display decoders / status word that the shadow-check suite pins out of every frontend file.
const FB = "fail" + "back";
const FL = "fall" + "back";
const RESERVED = [`ecco_${FL}`, `${FL.toUpperCase()}_PROFILE`, `${FB.toUpperCase()}_STATE`, `ecco_${FB}`, `${FB}_shadow`, "Shadow " + "Recovery", "fbc" + "_raw_", `${FL}_profile_live` + "_match", "ecco_" + "shadow_"];
const SCRIPTS = ["script.ecco_cfg_review_tou_slot_setting", "script.ecco_cfg_apply_tou_slot_setting", "script.ecco_cfg_acknowledge_edit_review"];

/** Strip comments (block and line) so that prose never satisfies or trips an authority pin. */
function codeOnly(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

// Routes to Home Assistant other than the service function (Window B H2): indirect invocation forms, the websocket, the page.
const ROUTE_RE: [RegExp, string][] = [
  [/\bReflect\b/, "Reflect"], [/\.apply\s*\(/, ".apply("], [/\.call\s*\(/, ".call("], [/\?\.\(/, "?.("], [/\(0,\s*\w+\)\s*\(/, "(0, f)("],
  [/fromCharCode/, "fromCharCode"], [/\bdocument\b/, "document"], [/\bglobalThis\b/, "globalThis"], [/\bself\s*\./, "self."],
  [/\bwindow\s*\.\s*(?:top|parent|opener|frames|location|open|postMessage)\b/, "window.<route>"], [/\bsocket\b/, "socket"],
  [/\bconnection\b/, "connection"], [/home-assistant/, "home-assistant element"], [/\bhass\s*\./, "hass.<prop> (the setter reads it once, through h)"],
];
const EXACT_IDS = ['"script.ecco_cfg_review_tou_slot_setting"', '"script.ecco_cfg_apply_tou_slot_setting"', '"script.ecco_cfg_acknowledge_edit_review"'];
// The identifier census: `call` in actions.ts (the parameter, the one invocation, the returned record's key and type) and `_call` in the
// element (the field, the setter, two null checks in the signature and the input, the guard and the one perform() argument, one more
// null check in the edit handler). Any further spelling is a second reference to the service function.
const CALL_WORDS_IN_ACTIONS = 4;
const UNDERSCORE_CALL_IN_ELEMENT = 7;

/** Window B S-2 / H2: the positive authority pins over the SOURCE. Returns every violation (an empty list is the proof). */
export function sourceAuthorityProblems(files: { name: string; text: string }[]): string[] {
  const out: string[] = [];
  for (const f of files) {
    const code = codeOnly(f.text);
    const calls = (code.match(/\bcall\s*\(/g) ?? []).length;
    if (f.name === "src/actions.ts") {
      if (calls !== 1) out.push(`${f.name}: ${calls} call sites, expected exactly 1`);
      if (!/\bcall\(c\.domain, c\.service, \{ entity_id: c\.data\.entity_id, variables: c\.data\.variables \}\)/.test(code)) out.push(`${f.name}: the one call does not have the fixed shape`);
      if (/\bcall\s*\(\s*"/.test(code)) out.push(`${f.name}: a call with a literal domain`);
      const words = (code.match(/\bcall\b/g) ?? []).length;
      if (words !== CALL_WORDS_IN_ACTIONS) out.push(`${f.name}: the identifier call appears ${words} times, expected ${CALL_WORDS_IN_ACTIONS}`);
      if ((code.match(/\bcall\s*[.?[]/g) ?? []).length) out.push(`${f.name}: the service function is used other than by the one direct call`);
    } else if (calls !== 0) {
      out.push(`${f.name}: ${calls} call site(s), expected 0`);
    }
    if (f.name === "src/ecco-tou-settings-card.ts") {
      const refs = (code.match(/_call\b/g) ?? []).length;
      if (refs !== UNDERSCORE_CALL_IN_ELEMENT) out.push(`${f.name}: _call appears ${refs} times, expected ${UNDERSCORE_CALL_IN_ELEMENT}`);
      if ((code.match(/_call\s*[(.?[]/g) ?? []).length) out.push(`${f.name}: _call is invoked or dereferenced directly`);
      if ((code.match(/\bperform\(this\._call,/g) ?? []).length !== 1) out.push(`${f.name}: perform(this._call, ...) must appear exactly once`);
      if ((code.match(/\bwindow\b/g) ?? []).length !== 2) out.push(`${f.name}: window must appear exactly twice (the card-picker registration)`);
      if ((code.match(/\.querySelector\s*\(/g) ?? []).length !== 1) out.push(`${f.name}: .querySelector( must appear exactly once (the shadow root's regions)`);
    } else {
      if (/_call\b/.test(code)) out.push(`${f.name}: _call outside the element`);
      if (/\bwindow\s*[.[]|\.querySelector\s*\(/.test(code)) out.push(`${f.name}: window or querySelector used outside the element`);
    }
    for (const [re, label] of ROUTE_RE) if (re.test(code)) out.push(`${f.name}: route ${label}`);
    for (const m of code.matchAll(/\bdomain:\s*"([^"]*)"/g)) if (m[1] !== "script") out.push(`${f.name}: domain literal "${m[1]}"`);
    for (const m of code.matchAll(/\bservice:\s*"([^"]*)"/g)) if (m[1] !== "turn_on") out.push(`${f.name}: service literal "${m[1]}"`);
    // comment markers inside string literals would hide code from a comment stripper: none are allowed in src/
    if (/(["'`])(?:(?!\1)[^\n\\]|\\.)*(?:\/\/|\/\*)(?:(?!\1)[^\n\\]|\\.)*\1/.test(f.text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1"))) out.push(`${f.name}: a comment marker inside a string literal`);
  }
  // src/types.ts declares the ServiceCall type with the same two literals; it is erased from the bundle, so the count is over code only.
  const all = files.filter((f) => f.name !== "src/types.ts").map((f) => codeOnly(f.text)).join("\n");
  const domains = (all.match(/\bdomain:\s*"script"/g) ?? []).length;
  const services = (all.match(/\bservice:\s*"turn_on"/g) ?? []).length;
  if (domains !== 3) out.push(`${domains} script domain literals, expected 3`);
  if (services !== 3) out.push(`${services} turn_on service literals, expected 3`);
  const ids = (all.match(/script\.ecco_cfg_[a-z_]+/g) ?? []).length;
  if (ids !== 3) out.push(`${ids} ACS1 script ids spelled, expected 3`);
  for (const id of EXACT_IDS) if ((all.match(new RegExp(id.replace(/[.]/g, "\\."), "g")) ?? []).length !== 1) out.push(`exact id ${id} not spelled exactly once`);
  for (const lit of FORBIDDEN_LITERALS) if (all.includes(`"${lit}"`)) out.push(`forbidden literal "${lit}"`);
  return out;
}

/** The same pins over the BUILT BUNDLE (minified names vary; shapes and literals do not). */
export function distAuthorityProblems(js: string): string[] {
  const out: string[] = [];
  const sites = (js.match(/\w+\(\w+\.domain,\w+\.service,\{entity_id:\w+\.data\.entity_id,variables:\w+\.data\.variables\}\)/g) ?? []).length;
  if (sites !== 1) out.push(`${sites} call sites of the fixed shape, expected exactly 1`);
  for (const m of js.matchAll(/\bdomain:"([^"]*)"/g)) if (m[1] !== "script") out.push(`domain literal "${m[1]}"`);
  for (const m of js.matchAll(/\bservice:"([^"]*)"/g)) if (m[1] !== "turn_on") out.push(`service literal "${m[1]}"`);
  if ((js.match(/\bdomain:"script"/g) ?? []).length !== 3) out.push("script domain literals != 3");
  if ((js.match(/"script"/g) ?? []).length !== 3) out.push('"script" literals != 3');
  if ((js.match(/"turn_on"/g) ?? []).length !== 3) out.push('"turn_on" literals != 3');
  if ((js.match(/script\.ecco_cfg_/g) ?? []).length !== 3) out.push("ACS1 script ids != 3");
  for (const id of EXACT_IDS) if ((js.match(new RegExp(id.replace(/[.]/g, "\\."), "g")) ?? []).length !== 1) out.push(`exact id ${id} not spelled exactly once`);
  if ((js.match(/callService/g) ?? []).length !== 2) out.push("callService spelled other than twice (the setter)");
  if ((js.match(/_call\s*[(.?[]/g) ?? []).length) out.push("_call invoked or dereferenced directly");
  if ((js.match(/querySelector\(/g) ?? []).length !== 1) out.push("querySelector other than once");
  if ((js.match(/\bwindow\b/g) ?? []).length !== 4) out.push("window other than four times (the card-picker registration)");
  for (const [re, label] of ROUTE_RE) if (label !== "hass.<prop> (the setter reads it once, through h)" && re.test(js)) out.push(`route ${label}`);
  for (const lit of FORBIDDEN_LITERALS) if (js.includes(`"${lit}"`)) out.push(`forbidden literal "${lit}"`);
  return out;
}

// Domain and service words that no allowed call uses; as quoted literals they are unambiguous in source and bundle alike. The Python
// wrapper (tools/tests/test_tou_settings_card.py) reads this very array, so the two suites share one list.
const FORBIDDEN_LITERALS = ["switch", "turn_off", "toggle", "press", "set_value", "select_option", "select_first", "select_next", "select_previous",
  "input_number", "input_text", "input_boolean", "input_select", "input_datetime", "input_button", "esphome", "homeassistant", "call_service",
  "perform_action", "automation", "persistent_notification", "modbus", "set_datetime", "reload", "cover", "open_cover", "close_cover", "scene",
  "light", "climate", "lock", "unlock", "fan", "media_player", "notify", "rest_command", "shell_command", "python_script", "hassio", "mqtt",
  "camera", "vacuum", "water_heater", "humidifier", "siren", "valve", "alarm_control_panel", "select", "turn_on_off"];

describe("authority in the source", () => {
  it("names no forbidden service, websocket, network, storage, event or dynamic-code API", () => {
    for (const s of sources) {
      for (const tok of FORBIDDEN) assert.ok(!s.text.includes(tok), `${s.name}: ${tok}`);
      for (const re of FORBIDDEN_RE) assert.ok(!re.test(s.text), `${s.name}: ${re}`);
    }
  });

  it("callService is read once, in the hass setter of the element, and never assigned to the card as the Home Assistant object", () => {
    const card = read(join(SRC, "ecco-tou-settings-card.ts"));
    assert.equal((card.match(/callService/g) ?? []).length, 3, "the shape, the typeof check and the bind, inside the setter");
    const setter = card.slice(card.indexOf("set hass("), card.indexOf("getCardSize"));
    assert.equal((setter.match(/callService/g) ?? []).length, 3, "all three inside the setter");
    assert.equal((card.match(/set hass\(/g) ?? []).length, 1);
    assert.ok(!/get hass\(/.test(card));
    assert.ok(!/this\.(?:_?hass)\b\s*=/.test(card));
    const uses = [...card.matchAll(/\bh\.([A-Za-z_]+)/g)].map((m) => m[1]);
    assert.deepEqual([...new Set(uses)].sort(), ["callService", "states"]);
    for (const s of sources) if (s.name !== "src/ecco-tou-settings-card.ts") assert.ok(!s.text.includes("callService"), s.name);
  });

  it("only actions.ts performs a call, and model.ts describes exactly the three script.turn_on targets", () => {
    assert.deepEqual(sourceAuthorityProblems(sources), []);
    const model = read(join(SRC, "model.ts"));
    for (const id of SCRIPTS) assert.equal((model.match(new RegExp(id.replace(/\./g, "\\."), "g")) ?? []).length, 1, id);
    assert.equal((all.match(/script\.ecco_cfg_/g) ?? []).length, 3, "the three ids are spelled once each, in model.ts");
  });

  it("S-2 mutation: a second hand-written call, of any domain, fails the source pins", () => {
    const actions = sources.find((s) => s.name === "src/actions.ts")!;
    const mutate = (extra: string) => sources.map((s) => (s.name === "src/actions.ts" ? { ...s, text: s.text.replace("return { call: c, done };", `${extra}\n  return { call: c, done };`) } : s));
    for (const extra of [
      'void call("switch", "turn_off", { entity_id: "switch.x" });',
      'void call("number", "set_value", { entity_id: "number.x", value: 1 });',
      'void call("script", "turn_on", { entity_id: "script.ecco_other" });',
      "void call(c.domain, c.service, { entity_id: c.data.entity_id, variables: c.data.variables });",
    ]) {
      const problems = sourceAuthorityProblems(mutate(extra));
      assert.ok(problems.length >= 1, `${extra}: ${problems.join("; ")}`);
    }
    // a call site added to another module
    const other = sources.map((s) => (s.name === "src/model.ts" ? { ...s, text: s.text + '\nexport function x(call: (d: string, s: string, p: object) => unknown) { return call("switch", "turn_off", { entity_id: "switch.x" }); }\n' } : s));
    assert.ok(sourceAuthorityProblems(other).length >= 1);
    // a fourth call description in model.ts
    const desc = sources.map((s) => (s.name === "src/model.ts" ? { ...s, text: s.text + '\nexport const EXTRA = { domain: "switch", service: "turn_off" };\n' } : s));
    assert.ok(sourceAuthorityProblems(desc).length >= 1);
    assert.ok(actions.text.includes("return { call: c, done };"), "the mutation anchor exists");
  });

  it("H2 mutation: Window B's M11-M14 and M4e/M4f (indirect calls, websocket and page routes) fail the source pins", () => {
    const EL = "src/ecco-tou-settings-card.ts";
    const SEND_ANCHOR = "this._sent = { kind, atMs: nowMs, resultBefore: stateText(this._states, H_RESULT) ?? \"\" };";
    const INFO_ANCHOR = "this._startInfo = !this._startInfo;";
    const RETURN_ANCHOR = "return { call: c, done };";
    const element = sources.find((s) => s.name === EL)!;
    const actions = sources.find((s) => s.name === "src/actions.ts")!;
    assert.ok(element.text.includes(SEND_ANCHOR) && element.text.includes(INFO_ANCHOR) && actions.text.includes(RETURN_ANCHOR), "the mutation anchors exist");
    const inElement = (extra: string, anchor: string) => sources.map((s) => (s.name === EL ? { ...s, text: s.text.replace(anchor, `${extra}\n    ${anchor}`) } : s));
    const inActions = (extra: string) => sources.map((s) => (s.name === "src/actions.ts" ? { ...s, text: s.text.replace(RETURN_ANCHOR, `${extra}\n  ${RETURN_ANCHOR}`) } : s));
    const mutants: [string, { name: string; text: string }[]][] = [
      ["M11 this._call cover.open_cover on every Review", inElement('if (kind === "review") void this._call("cover", "open_cover", { entity_id: "cover.garage" });', SEND_ANCHOR)],
      ["M12 the same, slot 5 only", inElement('if (kind === "review" && typeof payload !== "string" && payload.slot === 5) void this._call("cover", "open_cover", { entity_id: "cover.garage" });', SEND_ANCHOR)],
      ["M13 Reflect.apply(call, ...) scene.apply, slot 5", inActions('if (kind === "review" && c.data.variables.slot === 5) void Reflect.apply(call, undefined, ["scene", "apply", { entities: { "number.ecco_x": 100 } }]);')],
      ["M14 document.querySelector(home-assistant).hass.connection.socket.send on start-info", inElement('(globalThis as unknown as { document?: { querySelector?: (s: string) => { hass?: { connection?: { socket?: { send?: (m: string) => void } } } } | null } }).document?.querySelector?.("home-assistant")?.hass?.connection?.socket?.send?.(JSON.stringify({ id: 9, type: "config/entity_registry/update" }));', INFO_ANCHOR)],
      ["M4e aliased call with fromCharCode strings, on Acknowledge", inActions('const k = call; const dm = [115, 119, 105, 116, 99, 104].map((x) => String.fromCharCode(x)).join(""); const sv = [116, 117, 114, 110, 95, 111, 102, 102].map((x) => String.fromCharCode(x)).join(""); if (kind === "acknowledge") void k(dm, sv, { entity_id: c.data.entity_id });')],
      ["M4f the same, dormant on a slot-6 power Review", inActions('const k2 = call; const dm2 = [115, 119, 105, 116, 99, 104].map((x) => String.fromCharCode(x)).join(""); if (kind === "review" && c.data.variables.slot === 6 && c.data.variables.setting === "power") void k2(dm2, dm2, { entity_id: c.data.entity_id });')],
      ["M4g call.apply", inActions('if (kind === "review") void call.apply(undefined, ["cover", "open_cover", { entity_id: "cover.garage" }]);')],
      ["M4h (0, call)(...)", inActions('if (kind === "review") void (0, call)("cover", "open_cover", { entity_id: "cover.garage" });')],
      ["M4i call?.(...)", inActions('if (kind === "review") void call?.("cover", "open_cover", { entity_id: "cover.garage" });')],
      ["M15 a kept hass reference used later", inElement("void (this as unknown as { _h?: unknown })._h;", SEND_ANCHOR).map((s) => (s.name === EL ? { ...s, text: s.text.replace("this._render(false);\n  }", "this._render(false);\n    (this as unknown as { _h?: unknown })._h = hass; void (hass as { connection?: unknown })?.connection;\n  }") } : s))],
      ["M16 a hidden call behind a string comment marker", inActions('const u = "//"; void u; void call("cover", "open_cover", { entity_id: "cover.garage" });')],
    ];
    for (const [name, mutated] of mutants) {
      const problems = sourceAuthorityProblems(mutated);
      assert.ok(problems.length >= 1, `${name}: not caught`);
    }
  });

  it("listens for input, change and click only, and handles a fixed set of local actions", () => {
    const listeners = [...all.matchAll(/addEventListener\(\s*"([a-z]+)"/g)].map((m) => m[1]);
    assert.deepEqual(listeners.sort(), ["change", "click", "input"]);
    const emitted = new Set([...all.matchAll(/data-action="([a-z-]+)"/g)].map((m) => m[1]));
    assert.deepEqual([...emitted].sort(), ["ack", "ack-phrase", "apply", "cancel", "edit", "phrase", "review", "set-value", "start-info", "step", "undo", "value"]);
    const handled = new Set([...all.matchAll(/action (?:===|!==) "([a-z-]+)"/g)].map((m) => m[1]));
    assert.deepEqual([...handled].sort(), ["ack", "ack-phrase", "apply", "back", "cancel", "edit", "phrase", "review", "set-value", "start-info", "step", "undo", "value"]);
  });

  it("spells no reserved fallback / shadow token in any card file", () => {
    const files = [...sources.map((s) => s.text), dist, read(join(CARD, "README.md")), read(join(CARD, "examples", "tou-settings-example.yaml")),
      ...readdirSync(join(CARD, "test")).filter((f) => f.endsWith(".ts")).map((f) => read(join(CARD, "test", f)))];
    for (const text of files) for (const tok of RESERVED) assert.ok(!text.includes(tok), tok);
  });

  it("the device slug appears only as the quoted default; every dongle id is built from entity_prefix", () => {
    for (const s of sources) {
      const hits = [...s.text.matchAll(/ecco_clock_dongle[a-z0-9_]*/g)].map((m) => m[0]);
      assert.ok(hits.every((h) => h === "ecco_clock_dongle"), `${s.name}: ${hits}`);
    }
    assert.equal((all.match(/"ecco_clock_dongle"/g) ?? []).length, 2, "DEFAULT_ENTITY_PREFIX and the stub config");
  });

  it("the spacing rule is not configurable and start times have no editor path", () => {
    const model = read(join(SRC, "model.ts"));
    assert.ok(model.includes("export const APPLY_SPACING_S = 300;"));
    assert.ok(!/apply_spacing/.test(all));
    assert.ok(/EDITABLE: EditableSetting\[\] = \["target_soc", "power", "charge_source"\]/.test(model));
    const render = read(join(SRC, "render.ts"));
    assert.ok(!/data-setting="start_time"/.test(render));
    assert.ok(/START_TIME_LOCKED_TEXT/.test(render));
  });
});

describe("authority in the built bundle", () => {
  it("names no forbidden API and exactly the three script targets", () => {
    for (const tok of FORBIDDEN) assert.ok(!dist.includes(tok), tok);
    for (const re of FORBIDDEN_RE) assert.ok(!re.test(dist), String(re));
    for (const id of SCRIPTS) assert.equal((dist.match(new RegExp(id.replace(/\./g, "\\."), "g")) ?? []).length, 1, id);
    for (const tok of RESERVED) assert.ok(!dist.includes(tok), tok);
    assert.deepEqual(distAuthorityProblems(dist), []);
  });

  it("S-2 / H2 mutation: a second call, an indirect invocation or another route appended to the bundle fails the bundle pins", () => {
    const mutants = [
      ';n("switch","turn_off",{entity_id:"switch.x"})',
      ';n("number","set_value",{entity_id:"number.x",value:1})',
      ';n("script","turn_on",{entity_id:"script.ecco_other"})',
      ';n(r.domain,r.service,{entity_id:r.data.entity_id,variables:r.data.variables})',
      ';var q={domain:"switch",service:"toggle",data:{entity_id:"switch.x",variables:{}}}',
      ';e.callService("script","turn_on",{entity_id:"script.ecco_cfg_apply_tou_slot_setting"})',
      ';this._call("cover","open_cover",{entity_id:"cover.garage"})',
      ';Reflect.apply(e,void 0,["scene","apply",{}])',
      ';e.apply(void 0,["cover","open_cover",{}])',
      ';e.call(void 0,"cover","open_cover",{})',
      ';e?.("cover","open_cover",{})',
      ';(0,e)("cover","open_cover",{})',
      ';document.querySelector("home-assistant").hass.connection.socket.send("x")',
      ';String.fromCharCode(115)',
      ';window.parent.postMessage("x","*")',
      ';globalThis.hass.connection.sendMessagePromise({})',
      ';n("script","turn_on",{entity_id:"script.ecco_cfg_review_tou_slot_setting_v2"})',
    ];
    for (const m of mutants) {
      const problems = distAuthorityProblems(dist + m);
      assert.ok(problems.length >= 1, `${m}: ${problems.join("; ")}`);
    }
  });

  it("is self-contained: no import, no require, no source map, no local path, LF only", () => {
    assert.ok(!/(?:^|[;\n])\s*import\s*[\s{*"']/.test(dist));
    assert.ok(!/\brequire\s*\(/.test(dist));
    assert.ok(!dist.includes("sourceMappingURL"));
    assert.ok(!/[A-Za-z]:\\|\/Users\/|\/home\/|node_modules/.test(dist));
    assert.ok(!dist.includes("\r\n"));
  });

  it("listens for input, change and click only", () => {
    const listeners = [...dist.matchAll(/addEventListener\("([a-z]+)"/g)].map((m) => m[1]);
    assert.deepEqual([...new Set(listeners)].sort(), ["change", "click", "input"]);
  });
});
