import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { ADAPTER_BANS, CONTROL_CHARS } from "./support/staticBans.ts";

// Why this file exists: planAdapter.test.ts once held literal backspace bytes (0x08) where the regex word boundary \b was meant. Five of
// its static checks (hass, Date, fetch, document, window) therefore matched nothing and could never fail. These tests (1) scan every source
// of the card and the plan core for control characters, (2) prove that this scan detects the old defect, (3) prove that the old checks were
// vacuous and the current ones are not, and (4) prove that prose is not mistaken for code.

const BS = String.fromCharCode(8);
const here = fileURLToPath(new URL("./", import.meta.url));
const roots = [here, join(here, "..", "src"), join(here, "..", "..", "ecco-plan-core", "test"), join(here, "..", "..", "ecco-plan-core", "src")];

function listSources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (name === "node_modules") continue;
    if (statSync(p).isDirectory()) out.push(...listSources(p));
    else if (/\.(ts|mjs|js)$/.test(name) && !/\.min\.js$/.test(name)) out.push(p);
  }
  return out;
}

function controlCharsIn(text: string): { line: number; code: number }[] {
  const hits: { line: number; code: number }[] = [];
  text.split("\n").forEach((ln, i) => {
    for (const ch of ln) if (CONTROL_CHARS.test(ch)) hits.push({ line: i + 1, code: ch.charCodeAt(0) });
  });
  return hits;
}

test("no test or source file of the card and the plan core contains a control character", () => {
  const files = roots.flatMap(listSources);
  assert.ok(files.length > 30, "the scan must see the sources (saw " + files.length + ")");
  const bad: string[] = [];
  for (const f of files) {
    for (const h of controlCharsIn(readFileSync(f, "utf8"))) bad.push(f + ":" + h.line + " code " + h.code);
  }
  assert.deepEqual(bad, [], "control characters found");
});

test("the old defect is detected: a regex written with literal backspace bytes is flagged, a \\b regex is not", () => {
  const oldLine = "for (const bad of [/callService/, /" + BS + "hass" + BS + "/, /" + BS + "Date" + BS + "/, /localStorage/]) {";
  const hits = controlCharsIn(oldLine);
  assert.equal(hits.length, 4, "four backspace bytes in the reconstructed old line");
  assert.ok(hits.every((h) => h.code === 8 && h.line === 1));
  const newLine = "for (const bad of [/callService/, /\\bhass\\b/, /\\bDate\\b/, /localStorage/]) {";
  assert.deepEqual(controlCharsIn(newLine), []);
  assert.deepEqual(controlCharsIn("a\tb\r\nc"), [], "tab and carriage return are allowed");
  assert.equal(controlCharsIn("x" + String.fromCharCode(0) + "y").length, 1, "a NUL is flagged");
});

const VIOLATIONS: Record<string, string> = {
  hass: "export function f(hass) { return hass.callService; }",
  Date: "const now = Date.now();",
  fetch: "await fetch(url);",
  document: "document.body.append(x);",
  window: "window.location.href = u;",
};

test("the old backspace checks were vacuous (they matched none of the violations) and the current bans each fire", () => {
  for (const [word, snippet] of Object.entries(VIOLATIONS)) {
    const oldRe = new RegExp(BS + word + BS);
    assert.ok(!oldRe.test(snippet), "the old " + word + " check must not have matched " + snippet + " (it was vacuous)");
    assert.ok(ADAPTER_BANS.some((b) => b.test(snippet)), "a current ban must fire on " + snippet);
  }
  for (const snippet of ["const w = window;", "const x = typeof window;", "foo(window)"]) {
    assert.ok(ADAPTER_BANS.some((b) => b.test(snippet)), "a current ban must fire on " + snippet);
  }
});

test("prose is not mistaken for code: reason texts may name the charge window", () => {
  const prose = [
    '"No schedule is configured, so there is no charge window."',
    "raw[\"charge.windowStartMin\"] = checked(\"charge.windowStartMin\", start);",
    '"The scheduled charge end cannot be worked out (start or duration unreadable)."',
    "// states in, a plain snapshot out",
  ];
  for (const p of prose) {
    for (const b of ADAPTER_BANS) assert.ok(!b.test(p), p + " must not match " + b);
  }
});
