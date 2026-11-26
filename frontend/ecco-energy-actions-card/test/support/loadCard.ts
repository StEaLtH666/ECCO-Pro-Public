// Test support: bundle the real card element with esbuild (node platform, into the OS temp dir) so a test can construct it and call
// render() WITHOUT a browser DOM. Lit's node build supplies the HTMLElement / customElements shims; render() only returns a
// TemplateResult, which `flatten` turns into text. Nothing here touches the network or Home Assistant.
import { build } from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..", "..");

export interface RenderedCard {
  card: Record<string, unknown> & { render(): unknown; setConfig(c: unknown): void; hass?: unknown };
}

export async function loadCardClass(entry = "src/ecco-energy-actions-card.ts"): Promise<new () => RenderedCard["card"]> {
  const g = globalThis as Record<string, unknown>;
  g.window = g.window ?? {};
  const dir = mkdtempSync(join(tmpdir(), "eaa-card-"));
  const outfile = join(dir, "card.mjs");
  await build({
    entryPoints: [join(root, entry)],
    outfile,
    bundle: true,
    format: "esm",
    platform: "node",
    conditions: ["node"],
    target: ["node24"],
    logLevel: "silent",
    tsconfigRaw: { compilerOptions: { experimentalDecorators: true, useDefineForClassFields: false } },
  });
  const mod = (await import(pathToFileURL(outfile).href)) as Record<string, unknown>;
  const cls = mod.EccoEnergyActionsCard ?? (await import(pathToFileURL(outfile).href));
  return cls as new () => RenderedCard["card"];
}

const NOTHING = "\u0000nothing";

/** Text of a Lit TemplateResult tree: static strings joined with values; functions become [fn]; Lit `nothing`/null/false become "". */
export function flatten(v: unknown): string {
  if (v === null || v === undefined || v === false || v === true) return "";
  if (typeof v === "string" || typeof v === "number") return String(v);
  if (typeof v === "function") return "[fn]";
  if (Array.isArray(v)) return v.map(flatten).join("");
  const o = v as { strings?: readonly string[]; values?: unknown[]; _$litType$?: unknown };
  if (o && o.strings && o.values) {
    let out = "";
    o.strings.forEach((s, i) => {
      out += s;
      if (i < (o.values as unknown[]).length) out += flatten((o.values as unknown[])[i]);
    });
    return out;
  }
  // Lit's `nothing` is a symbol; other symbols/objects carry no text.
  return typeof v === "symbol" ? "" : NOTHING.slice(0, 0);
}
