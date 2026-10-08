// The committed bundle is exactly what `node build.mjs` produces from these sources (deterministic build), and the package
// metadata matches the other ECCO cards' conventions.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

import { normalizeConfig } from "../src/model.ts";

const CARD = join(dirname(fileURLToPath(import.meta.url)), "..");
const DIST = join(CARD, "dist", "ecco-weather-solar-card.js");
const sha = (b: Buffer): string => createHash("sha256").update(b).digest("hex");
const haveEsbuild = existsSync(join(CARD, "node_modules", "esbuild", "package.json"));

describe("deterministic build", () => {
  it("rebuilding twice gives byte-identical output, equal to the committed dist", { skip: haveEsbuild ? false : "esbuild is not installed (run npm ci)" }, () => {
    const dir = mkdtempSync(join(tmpdir(), "ecco-wsc-"));
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

  it("the bundle carries the card tag and version, LF line endings", () => {
    const js = readFileSync(DIST, "utf8");
    assert.ok(js.includes('"0.1.0"'));
    assert.ok(js.includes("ecco-weather-solar-card"));
    assert.ok(!js.includes("\r\n"));
  });
});

describe("package metadata", () => {
  const pkg = JSON.parse(readFileSync(join(CARD, "package.json"), "utf8")) as Record<string, unknown>;
  const lock = JSON.parse(readFileSync(join(CARD, "package-lock.json"), "utf8")) as {
    lockfileVersion: number;
    name: string;
    packages: Record<string, { name?: string; version?: string; license?: string; devDependencies?: Record<string, string> }>;
  };

  it("is private, GPL-3.0-or-later, with no runtime dependencies and exactly pinned build tools", () => {
    assert.equal(pkg.name, "ecco-weather-solar-card");
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
    assert.equal(lock.name, "ecco-weather-solar-card");
    const root = lock.packages[""]!;
    assert.equal(root.name, "ecco-weather-solar-card");
    assert.equal(root.license, "GPL-3.0-or-later");
    assert.deepEqual(root.devDependencies, pkg.devDependencies);
    const dev = pkg.devDependencies as Record<string, string>;
    assert.equal(lock.packages["node_modules/esbuild"]?.version, dev.esbuild);
    assert.equal(lock.packages["node_modules/typescript"]?.version, dev.typescript);
  });

  it("hacs.json names the built file", () => {
    const hacs = JSON.parse(readFileSync(join(CARD, "hacs.json"), "utf8")) as Record<string, unknown>;
    assert.equal(hacs.filename, "ecco-weather-solar-card.js");
    assert.ok(existsSync(DIST));
  });

  it("the example Lovelace configuration is accepted by the card and names the default entities", () => {
    const text = readFileSync(join(CARD, "examples", "weather-solar-example.yaml"), "utf8");
    const cfg: Record<string, unknown> = {};
    let section: Record<string, unknown> | null = null;
    for (const line of text.split("\n")) {
      if (/^\s*(#|$)/.test(line)) continue;
      const top = /^([a-z_]+):\s*(.*?)\s*$/.exec(line);
      const sub = /^ {2}([a-z_]+):\s*(.*?)\s*$/.exec(line);
      const val = (raw: string): unknown => {
        const s = raw.replace(/^"(.*)"$/, "$1");
        return /^\d+$/.test(s) ? Number(s) : s === "true" ? true : s === "false" ? false : s;
      };
      if (top && top[1]) {
        if (top[2] === "") {
          section = {};
          cfg[top[1]] = section;
        } else {
          section = null;
          cfg[top[1]] = val(top[2] ?? "");
        }
      } else if (sub && sub[1] && section) section[sub[1]] = val(sub[2] ?? "");
    }
    assert.equal(cfg.type, "custom:ecco-weather-solar-card");
    const c = normalizeConfig(cfg);
    assert.equal(c.entities.weather, "weather.forecast_home");
    assert.equal(c.entities.pv_energy_statistic, "sensor.ecco_clock_dongle_ecco_total_pv_energy");
  });
});
