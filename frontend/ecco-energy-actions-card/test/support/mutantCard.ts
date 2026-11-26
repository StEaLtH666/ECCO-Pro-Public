// Test support: the real card bundled from a SOURCE MUTANT (one exact text replacement in one file of the card or of the plan core), so a test can run
// its end-to-end checks against code that has lost a safety-relevant line. The mutated copy lives in the OS temp dir and is deleted again; nothing in the
// repository changes. Same technique as the mutants of test/planControls.test.ts (which keeps its own copy of this loader, unchanged).
import { build } from "esbuild";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const cardRoot = resolve(import.meta.dirname, "..", "..");
const coreRoot = resolve(cardRoot, "..", "ecco-plan-core");
let mutantCount = 0;

export type CardCtor = new () => { render(): unknown; setConfig(c: unknown): void; hass?: unknown; [k: string]: unknown };

/** The card class bundled from the source tree with `find` replaced by `put` in `file` (a path under src/, or "core/..." under the plan core's src/). */
export async function loadMutantCard(file: string, find: string, put: string, times = 1): Promise<CardCtor> {
  const dir = mkdtempSync(join(tmpdir(), "eaa-mut-"));
  try {
    cpSync(join(cardRoot, "src"), join(dir, "frontend", "ecco-energy-actions-card", "src"), { recursive: true });
    cpSync(join(coreRoot, "src"), join(dir, "frontend", "ecco-plan-core", "src"), { recursive: true });
    const base = file.startsWith("core/") ? join(dir, "frontend", "ecco-plan-core", "src", file.slice(5)) : join(dir, "frontend", "ecco-energy-actions-card", "src", file);
    const cardFile = join(dir, "frontend", "ecco-energy-actions-card", "src", "ecco-energy-actions-card.ts");
    writeFileSync(cardFile, readFileSync(cardFile, "utf8").replace('@customElement("ecco-energy-actions-card")', '@customElement("ecco-energy-actions-card-epoch-mutant-' + String(++mutantCount) + '")'));
    const text = readFileSync(base, "utf8");
    const n = text.split(find).length - 1;
    assert.equal(n, times, "mutant anchor " + JSON.stringify(find.slice(0, 70)) + " found " + n + "x in " + file);
    writeFileSync(base, text.split(find).join(put));
    const g = globalThis as Record<string, unknown>;
    g.window = g.window ?? {};
    const outfile = join(dir, "card.mjs");
    await build({
      entryPoints: [join(dir, "frontend", "ecco-energy-actions-card", "src", "ecco-energy-actions-card.ts")], outfile, bundle: true, format: "esm", platform: "node",
      conditions: ["node"], target: ["node24"], logLevel: "silent", nodePaths: [join(cardRoot, "node_modules")],
      tsconfigRaw: { compilerOptions: { experimentalDecorators: true, useDefineForClassFields: false } },
    });
    const mod = (await import(pathToFileURL(outfile).href)) as Record<string, unknown>;
    return mod.EccoEnergyActionsCard as CardCtor;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** The card class bundled from the unchanged sources as a module instance of its own (a second `loadCardClass` would register the element name twice), so module state such as the click memory starts empty. */
export function loadFreshCard(): Promise<CardCtor> {
  return loadMutantCard("plan/clock.ts", "const DAY_MS = 86_400_000;", "const DAY_MS = 86_400_000;");
}
