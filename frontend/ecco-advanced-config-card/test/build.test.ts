// The committed bundle is exactly what `node build.mjs` produces from these sources (deterministic build), and the
// package metadata matches the other ECCO cards' conventions.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { CATALOGUE_SHA256 } from "../src/catalogue.generated.ts";
import { normalizeConfig } from "../src/model.ts";

const CARD = join(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = join(CARD, "dist", "ecco-advanced-config-card.js");
const sha = (b: Buffer): string => createHash("sha256").update(b).digest("hex");
const haveEsbuild = existsSync(join(CARD, "node_modules", "esbuild", "package.json"));

describe("deterministic build", () => {
  it("rebuilding twice gives byte-identical output, equal to the committed dist", { skip: haveEsbuild ? false : "esbuild is not installed (run npm ci)" }, () => {
    const dir = mkdtempSync(join(tmpdir(), "ecco-advcfg-"));
    try {
      const outs = [join(dir, "a.js"), join(dir, "b.js")];
      for (const out of outs) execFileSync(process.execPath, ["build.mjs", "--outfile", out], { cwd: CARD, stdio: "pipe" });
      const [a, b] = outs.map((o) => readFileSync(o));
      assert.equal(sha(a!), sha(b!));
      assert.equal(sha(a!), sha(readFileSync(DIST)), "dist/ is stale: run `npm run build` and commit the result");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("the bundle embeds the current catalogue and the card version", () => {
    const js = readFileSync(DIST, "utf8");
    assert.ok(js.includes(CATALOGUE_SHA256));
    assert.ok(js.includes('"0.1.0"'));
    assert.ok(js.includes("ecco-advanced-config-card"));
    assert.ok(!js.includes("\r\n"), "LF line endings");
  });
});

describe("package metadata", () => {
  const pkg = JSON.parse(readFileSync(join(CARD, "package.json"), "utf8")) as Record<string, unknown>;
  const lock = JSON.parse(readFileSync(join(CARD, "package-lock.json"), "utf8")) as {
    lockfileVersion: number;
    packages: Record<string, { version?: string; license?: string; devDependencies?: Record<string, string> }>;
  };

  it("is private, GPL-3.0-or-later, with no runtime dependencies and exactly pinned build tools", () => {
    assert.equal(pkg.name, "ecco-advanced-config-card");
    assert.equal(pkg.private, true);
    assert.equal(pkg.type, "module");
    assert.equal(pkg.license, "GPL-3.0-or-later");
    assert.equal(pkg.dependencies, undefined);
    const dev = pkg.devDependencies as Record<string, string>;
    assert.deepEqual(Object.keys(dev).sort(), ["esbuild", "typescript"]);
    for (const v of Object.values(dev)) assert.match(v, /^\d+\.\d+\.\d+$/);
    assert.deepEqual(pkg.scripts, { build: "node build.mjs", typecheck: "tsc --noEmit -p tsconfig.json", test: 'node --test "test/*.test.ts"' });
  });

  it("the lockfile agrees with package.json", () => {
    assert.equal(lock.lockfileVersion, 3);
    const root = lock.packages[""]!;
    assert.equal(root.license, "GPL-3.0-or-later");
    assert.deepEqual(root.devDependencies, pkg.devDependencies);
    const dev = pkg.devDependencies as Record<string, string>;
    assert.equal(lock.packages["node_modules/esbuild"]?.version, dev.esbuild);
    assert.equal(lock.packages["node_modules/typescript"]?.version, dev.typescript);
  });

  it("hacs.json names the built file", () => {
    const hacs = JSON.parse(readFileSync(join(CARD, "hacs.json"), "utf8")) as Record<string, unknown>;
    assert.equal(hacs.filename, "ecco-advanced-config-card.js");
    assert.ok(existsSync(DIST));
  });

  it("the example Lovelace configuration is accepted by the card", () => {
    const text = readFileSync(join(CARD, "examples", "advanced-config-example.yaml"), "utf8");
    const cfg: Record<string, unknown> = {};
    for (const line of text.split("\n")) {
      const m = /^([a-z_]+):\s*(.*?)\s*$/.exec(line);
      if (!m || !m[1]) continue;
      const raw = (m[2] ?? "").replace(/^"(.*)"$/, "$1");
      cfg[m[1]] = /^\d+$/.test(raw) ? Number(raw) : raw;
    }
    assert.equal(cfg.type, "custom:ecco-advanced-config-card");
    const c = normalizeConfig(cfg);
    assert.equal(c.entity_prefix, "ecco_clock_dongle");
  });
});
