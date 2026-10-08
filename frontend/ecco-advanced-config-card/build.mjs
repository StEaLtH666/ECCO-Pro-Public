// Build script for the ECCO Advanced / Experimental Configuration card.
//
// Bundles src/ecco-advanced-config-card.ts (with the generated catalogue) into one dependency-free browser file,
// dist/ecco-advanced-config-card.js - the HACS "plugin" (Lovelace resource) shape. The card has no runtime
// dependencies, so the bundle contains only this project's own code.
//
// Deterministic: same sources + same esbuild version = byte-identical output (no timestamps, no source maps, no
// absolute paths). test/build.test.ts rebuilds into a temporary file and compares it with dist/.
//
// Usage:
//   node build.mjs                      write dist/ecco-advanced-config-card.js
//   node build.mjs --outfile <path>     write somewhere else (used by the reproducibility test)

import { build } from "esbuild";

const i = process.argv.indexOf("--outfile");
const outfile = i > 0 && process.argv[i + 1] ? process.argv[i + 1] : "dist/ecco-advanced-config-card.js";

export const OPTIONS = {
  entryPoints: ["src/ecco-advanced-config-card.ts"],
  outfile,
  bundle: true,
  format: "esm",
  target: ["es2021"],
  minify: true,
  sourcemap: false,
  legalComments: "none",
  charset: "utf8",
  logLevel: "warning",
};

await build(OPTIONS);
console.log(`Built ${outfile}`);
