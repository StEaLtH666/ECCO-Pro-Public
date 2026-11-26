// Mutants of the Gentle night planner's own logic. Each entry (test/support/gentleNightProbe.ts) changes ONE line of src/gentleNight.ts (the source text is
// edited and imported from a temporary file); the probe's summary of the mutant must differ from the COMMITTED golden summary (test/gentleNightProbe.golden.json)
// in at least one of the named keys, or the mutant "survived" and the test fails. The real source must equal the golden in every key, so this file is also
// a regression guard: a deliberate behaviour change regenerates the golden (node test/support/writeNightProbeGolden.ts) and the diff shows in review.
// The kill here is against the golden; the kill against the behavioural assertion suites is measured by tools/night_mutation_score.py (README).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import * as here from "../src/gentleNight.ts";
import { MUTANTS, signature } from "./support/gentleNightProbe.ts";
import type { Mod } from "./support/gentleNightProbe.ts";

const GOLDEN_RAW = JSON.parse(readFileSync(new URL("./gentleNightProbe.golden.json", import.meta.url), "utf8")) as Record<string, unknown>;
const GOLDEN: Record<string, string> = Object.fromEntries(Object.entries(GOLDEN_RAW).map(([k, v]) => [k, JSON.stringify(v)]));
const keys = Object.keys(GOLDEN);
const SRC = readFileSync(new URL("../src/gentleNight.ts", import.meta.url), "utf8");

test("the probe is a function of the module: two runs on the real source agree, it has enough behaviours, and none throws", () => {
  const a = signature(here);
  assert.deepEqual(signature(here), a);
  assert.ok(keys.length >= 60, "behaviours probed: " + keys.length);
  for (const k of keys) assert.notEqual(a[k], "THROW", "the real source must not throw in " + k);
});

test("regression guard: the real source equals the committed golden probe in every key (a deliberate change regenerates the golden and shows in review)", () => {
  const a = signature(here);
  assert.deepEqual(Object.keys(a).sort(), [...keys].sort(), "the probe's keys and the golden's keys");
  for (const k of keys) assert.equal(a[k], GOLDEN[k], "behaviour '" + k + "' moved from the committed golden");
});

test("the mutant list is long enough and every anchor occurs exactly once in the source", () => {
  assert.ok(MUTANTS.length >= 90, "mutants: " + MUTANTS.length);
  for (const mu of MUTANTS) {
    assert.equal(SRC.split(mu.from).length, 2, "the anchor of '" + mu.id + "' must occur exactly once");
    assert.notEqual(mu.from, mu.to);
    for (const k of mu.keys) assert.ok(keys.includes(k), "unknown key " + k);
  }
  assert.equal(new Set(MUTANTS.map((mu) => mu.id)).size, MUTANTS.length, "mutant ids are unique");
});

for (const mu of MUTANTS) {
  test("mutant killed: " + mu.id, async () => {
    const dir = mkdtempSync(join(tmpdir(), "gentle-night-mut-"));
    try {
      const u = (name: string): string => new URL("../src/" + name, import.meta.url).href;
      const mutated = SRC.replace(mu.from, mu.to)
        .replaceAll('from "./gentleController.ts"', 'from "' + u("gentleController.ts") + '"')
        .replaceAll('from "./time.ts"', 'from "' + u("time.ts") + '"')
        .replaceAll('from "./settings.ts"', 'from "' + u("settings.ts") + '"')
        .replaceAll('from "./tou.ts"', 'from "' + u("tou.ts") + '"');
      const file = join(dir, "gentleNight.mut.ts");
      writeFileSync(file, mutated, "utf8");
      const m = (await import(pathToFileURL(file).href)) as Mod;
      const sig = signature(m);
      const differing = keys.filter((k) => sig[k] !== GOLDEN[k]);
      assert.ok(differing.length > 0, "the mutant survived: nothing differs from the golden");
      assert.ok(mu.keys.some((k) => differing.includes(k)), "expected one of " + mu.keys.join(",") + " to differ; differing: " + differing.join(","));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
}
