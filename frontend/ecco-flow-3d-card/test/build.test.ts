// Bundle determinism: building twice gives byte-identical output, and the
// committed dist matches a fresh build of the committed sources. The two
// rebuild tests need esbuild (npm ci); where it is not installed (CI installs
// no npm package) they are reported as skipped, never as passed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const card = fileURLToPath(new URL("..", import.meta.url));
// Hashes are taken over LF-normalised content: the repository checks files
// out with CRLF on Windows (core.autocrlf), while esbuild always writes LF.
const sha = (p: string) => createHash("sha256").update(readFileSync(p, "utf-8").replace(/\r\n/g, "\n")).digest("hex");

type Build = (options: Record<string, unknown>) => Promise<unknown>;
let esbuild: Build | null = null;
try {
  esbuild = ((await import("esbuild")) as { build: Build }).build;
} catch {
  esbuild = null;
}
const needsEsbuild = esbuild ? false : "esbuild is not installed (run `npm ci` in the card folder)";

async function bundleTo(outfile: string): Promise<void> {
  await esbuild!({
    entryPoints: [join(card, "src", "ecco-flow-3d-card.ts")],
    outfile,
    bundle: true,
    format: "esm",
    target: ["es2021"],
    minify: true,
    sourcemap: false,
    legalComments: "eof",
    logLevel: "silent",
    absWorkingDir: card,
  });
}

test("two builds of the same sources are byte-identical", { skip: needsEsbuild }, async () => {
  const dir = mkdtempSync(join(tmpdir(), "ecco-flow-3d-build-"));
  try {
    const a = join(dir, "a.js");
    const b = join(dir, "b.js");
    await bundleTo(a);
    await bundleTo(b);
    assert.equal(sha(a), sha(b));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("dist/ecco-flow-3d-card.js is the build of the current sources", { skip: needsEsbuild }, async () => {
  const dir = mkdtempSync(join(tmpdir(), "ecco-flow-3d-dist-"));
  try {
    const fresh = join(dir, "fresh.js");
    await bundleTo(fresh);
    assert.equal(sha(join(card, "dist", "ecco-flow-3d-card.js")), sha(fresh), "run `npm run build` and commit dist/ when the sources change");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the bundle keeps the Lit licence notice and is a self-contained ES module", () => {
  const bundle = readFileSync(join(card, "dist", "ecco-flow-3d-card.js"), "utf-8");
  assert.match(bundle, /Copyright .* Google LLC/);
  assert.doesNotMatch(bundle, /^\s*import\s.*from\s*["']/m, "no bare module imports remain");
  assert.ok(bundle.length < 200 * 1024, "stays a small single file");
});
