import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { canStartExport, checkStopSoc, compileInvariantViolations, isRaiseOnly } from "../src/guards.ts";
import { compileTou } from "../src/tou.ts";
import * as pkg from "../src/index.ts";
import { exampleBaseline } from "./fixtures.ts";

test("Stop SOC: only whole numbers 10-90 pass; everything else is refused", () => {
  for (let v = -50; v <= 150; v++) assert.equal(checkStopSoc(v).allowed, v >= 10 && v <= 90, "stop " + v);
  for (const v of [10.5, NaN, Infinity, "30", null, undefined]) assert.equal(checkStopSoc(v).allowed, false);
});

test("an export start is refused while controlLocked is true, and also when it is not an explicit false", () => {
  const ctx = { controlLocked: false, stopSoc: 30, backupReservePct: 20 };
  assert.equal(canStartExport(ctx).allowed, true);
  assert.equal(canStartExport({ ...ctx, controlLocked: true }).allowed, false);
  assert.match(canStartExport({ ...ctx, controlLocked: true }).reasons[0] as string, /locked/);
  for (const bad of [undefined, null, 0, "false"]) assert.equal(canStartExport({ ...ctx, controlLocked: bad as unknown as boolean }).allowed, false);
  assert.equal(canStartExport({ ...ctx, transactionOwner: "dump" }).allowed, false);
  assert.equal(canStartExport({ ...ctx, stopSoc: 15 }).allowed, false, "below the enforced reserve");
  assert.equal(canStartExport({ ...ctx, stopSoc: 5 }).allowed, false);
});

test("a locked control means no compiled plan has an export in it, whatever else is requested", () => {
  const r = compileTou({ baseline: exampleBaseline(), intervals: [{ action: "export", startMin: 1170, durationMin: 150, powerW: 3000, targetSoc: 30 }], controlLocked: true });
  assert.equal(r.refused.length, 1);
  assert.ok(r.slotReports.every((s) => s.origin !== "derived:export"));
  assert.deepEqual(compileInvariantViolations(r), []);
});

test("raise-only helper", () => {
  assert.equal(isRaiseOnly(50, 80), true);
  assert.equal(isRaiseOnly(50, 50), true);
  assert.equal(isRaiseOnly(50, 49), false);
});

const SRC = fileURLToPath(new URL("../src/", import.meta.url));
const files = readdirSync(SRC).filter((f) => f.endsWith(".ts"));
// Comments are stripped so that prose may mention these words; code may not use them.
const raw = (f: string) => readFileSync(SRC + f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'])\/\/.*$/gm, "$1");
// String literal contents are blanked too, so user-facing prose can neither trip nor hide a check.
const code = (f: string) => raw(f).replace(/"(?:[^"\\\n]|\\.)*"/g, '""');

test("static: the package imports only its own files (no DOM, Home Assistant, Node or network module)", () => {
  assert.ok(files.length >= 8);
  for (const f of files) {
    const imports = [...raw(f).matchAll(/^(?:import|export)\s+(?:type\s+)?(?:\*|\{[^}]*\})\s*from\s+"([^"]+)"/gm)].map((m) => m[1] as string);
    for (const spec of imports) assert.match(spec, /^\.\/[A-Za-z]+\.ts$/, f + " imports " + spec);
    assert.doesNotMatch(code(f), /\bimport\s*\(/, f + " has a dynamic import");
    assert.doesNotMatch(code(f), /\brequire\s*\(/, f);
  }
});

test("static: no source touches the DOM, Home Assistant, the network, storage, the clock, randomness or the environment", () => {
  const banned = [/\bdocument\b/, /\bwindow\b/, /\bglobalThis\b/, /\bfetch\s*\(/, /XMLHttpRequest/, /WebSocket/, /EventSource/, /sendBeacon/, /\bhass\b/i, /callService/, /callWS/, /customElements/, /localStorage/, /sessionStorage/, /indexedDB/, /\bprocess\b/, /\bDate\b/, /Math\.random/, /setTimeout|setInterval/, /\beval\s*\(/, /new Function/, /\bconsole\./];
  for (const f of files) for (const b of banned) assert.doesNotMatch(code(f), b, f + " matches " + b);
});

test("static: the public surface is data and pure functions only (no class, no setter, no async, no write verb)", () => {
  for (const f of files) {
    assert.doesNotMatch(code(f), /\bclass\s/, f);
    assert.doesNotMatch(code(f), /\basync\b|\bawait\b|\bPromise\b/, f);
  }
  for (const [name, value] of Object.entries(pkg)) {
    assert.doesNotMatch(name, /^(write|send|call|post|put|set[A-Z]|execute|dispatch|publish|save|push)/, "export " + name + " sounds like a write");
    assert.ok(typeof value === "function" || typeof value === "object" || typeof value === "number" || typeof value === "string", name);
  }
});
