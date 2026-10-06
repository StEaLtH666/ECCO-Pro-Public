// Build script for the ECCO Energy Actions Card.
//
// Bundles src/ecco-energy-actions-card.ts into a single, dependency-free
// browser file at dist/ecco-energy-actions-card.js - same HACS "plugin"
// (Lovelace resource) shape as the sibling ecco-energy-flow-card: one
// <script type="module"> file a user adds as a dashboard resource, no
// build step required on their end.
//
// Usage:
//   node build.mjs          one-off production build (minified)
//   node build.mjs --watch  rebuild on change, unminified, with inline sourcemap

import { build, context } from "esbuild";

const watch = process.argv.includes("--watch");

const options = {
  entryPoints: ["src/ecco-energy-actions-card.ts"],
  outfile: "dist/ecco-energy-actions-card.js",
  bundle: true,
  format: "esm",
  target: ["es2021"],
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  legalComments: "eof",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("Watching for changes...");
} else {
  await build(options);
  console.log("Built dist/ecco-energy-actions-card.js");
}
