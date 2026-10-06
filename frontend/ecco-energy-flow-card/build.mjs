// Build script for the ECCO Energy Flow Card prototype.
//
// Bundles src/ecco-energy-flow-card.ts into a single, dependency-free
// browser file at dist/ecco-energy-flow-card.js - the standard HACS
// "plugin" (Lovelace resource) shape: one <script type="module"> file a
// user adds as a dashboard resource, no build step required on their end.
//
// Usage:
//   node build.mjs          one-off production build (minified)
//   node build.mjs --watch  rebuild on change, unminified, with inline sourcemap

import { build, context } from "esbuild";

const watch = process.argv.includes("--watch");

const options = {
  entryPoints: ["src/ecco-energy-flow-card.ts"],
  outfile: "dist/ecco-energy-flow-card.js",
  bundle: true,
  format: "esm",
  target: ["es2021"],
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  // Keep the bundled third-party licence notices (Lit: BSD-3-Clause) at the end of the bundle; see THIRD_PARTY_NOTICES.md.
  legalComments: "eof",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("Watching for changes...");
} else {
  await build(options);
  console.log("Built dist/ecco-energy-flow-card.js");
}
