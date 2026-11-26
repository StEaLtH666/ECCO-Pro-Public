// Build script for the ECCO 3D Energy Flow card.
//
// Bundles src/ecco-flow-3d-card.ts into one dependency-free browser module at
// dist/ecco-flow-3d-card.js (the HACS "plugin" / Lovelace resource shape).
// The build is deterministic: same sources and lockfile -> byte-identical
// output (test/build.test.ts checks this), so a bundle hash identifies a
// source state exactly, as the other ECCO cards' install kits expect.
//
//   node build.mjs          production build (minified)
//   node build.mjs --watch  rebuild on change, unminified, inline sourcemap

import { build, context } from "esbuild";

const watch = process.argv.includes("--watch");

export const options = {
  entryPoints: ["src/ecco-flow-3d-card.ts"],
  outfile: "dist/ecco-flow-3d-card.js",
  bundle: true,
  format: "esm",
  target: ["es2021"],
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  legalComments: "eof",
  logLevel: "warning",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("Watching for changes...");
} else {
  await build(options);
  console.log("Built dist/ecco-flow-3d-card.js");
}
