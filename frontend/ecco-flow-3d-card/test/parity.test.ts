// The power model must stay identical to the installed ECCO Energy Flow
// card's. These tests import BOTH implementations and compare them, and pin
// the motion constants against that card's source text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import * as mine from "../src/core/power.ts";
import * as mineConfig from "../src/config.ts";
import * as motion from "../src/core/motion.ts";
import * as theirs from "../../ecco-energy-flow-card/src/config.ts";
import * as myFormat from "../src/core/format.ts";
import * as theirFormat from "../../ecco-energy-flow-card/src/utils/format.ts";

const vectors = [0, 1, -1, 5, -5, 149, 150, 151, 500, -500, 1240, 1810, 3050, 6000, 6001, 9999];

test("battery and grid sign normalisation agree with the Energy Flow card", () => {
  for (const w of vectors) {
    for (const sign of ["charge_positive", "discharge_positive", undefined] as const) {
      assert.equal(mine.normaliseBatteryPower(w, sign), theirs.normaliseBatteryPower(w, sign), `battery ${w} ${sign}`);
    }
    for (const sign of ["import_positive", "export_positive", undefined] as const) {
      assert.equal(mine.normaliseGridPower(w, sign), theirs.normaliseGridPower(w, sign), `grid ${w} ${sign}`);
    }
  }
});

test("resolveHomeW agrees with the Energy Flow card on every combination, including the fallback margin", () => {
  assert.equal(mine.HOME_FALLBACK_MIN_W, theirs.HOME_FALLBACK_MIN_W);
  const options = [null, ...vectors];
  for (const n of options) {
    for (const i of options) {
      for (const g of options) {
        assert.equal(mine.resolveHomeW(n, i, g), theirs.resolveHomeW(n, i, g), `home(${n}, ${i}, ${g})`);
      }
    }
  }
});

test("solar sources normalise the same way (object or array, unset entries dropped)", () => {
  const cases = [undefined, { power: "a" }, [{ power: "a" }, { label: "x" }, { power: "b" }], [{}]];
  for (const c of cases) {
    assert.deepEqual(mineConfig.normaliseSolarSources(c as never), theirs.normaliseSolarSources(c as never));
  }
});

test("Solar Share is the production Overview's definition: today's solar over today's load, clamped, rounded", () => {
  // The Overview (ecco-energy-flow-card, features.solar_contribution: true on ecco_pro) shows
  // formatPercent(solar / load) and hides it when the load is unknown or not positive.
  const src = readFileSync(new URL("../../ecco-energy-flow-card/src/ecco-energy-flow-card.ts", import.meta.url), "utf-8");
  assert.match(src, /private _solarShareText\(\)[\s\S]*?if \(!load \|\| load <= 0\) return null;\s*const solar = this\._numeric\(today\.solar\) \?\? 0;\s*return formatPercent\(solar \/ load\);/);
  const dash = readFileSync(new URL("../../../home-assistant/dashboards/ecco_pro.yaml", import.meta.url), "utf-8");
  assert.match(dash, /solar_contribution: true/, "the production Overview enables it");
  const samples: Array<[number, number]> = [[0, 10], [3.2, 14.2], [10.8, 14.2], [14.2, 14.2], [20, 14.2], [0.04, 0.5], [7.5, 0.1]];
  for (const [solar, load] of samples) {
    const share = myFormat.solarShareFraction(solar, load);
    assert.equal(share === null ? "--" : myFormat.formatPercent(share * 100), theirFormat.formatPercent(solar / load), `${solar} / ${load}`);
  }
  assert.equal(myFormat.solarShareFraction(5, 0), null, "no share without a positive load (the Overview hides it)");
  assert.equal(myFormat.solarShareFraction(5, null), null);
  assert.equal(myFormat.solarShareFraction(null, 10), null, "an unknown solar reading is unknown here, not 0 %");
});

test("motion constants match the Energy Flow card's tuned values", () => {
  const src = readFileSync(new URL("../../ecco-energy-flow-card/src/ecco-energy-flow-card.ts", import.meta.url), "utf-8");
  const constant = (name: string): number => {
    const m = new RegExp(`const ${name} = ([0-9.]+);`).exec(src);
    assert.ok(m, `constant ${name} found in the Energy Flow card`);
    return Number(m![1]);
  };
  assert.equal(motion.MAX_ANIMATION_MAGNITUDE_W, constant("MAX_ANIMATION_MAGNITUDE_W"));
  assert.equal(motion.INTENSITY_EXPONENT, constant("INTENSITY_EXPONENT"));
  assert.equal(motion.MIN_DURATION_S, constant("MIN_DURATION_S"));
  assert.equal(motion.MAX_DURATION_S, constant("MAX_DURATION_S"));
  assert.equal(motion.MIN_BALL_DURATION_S, constant("MIN_BALL_DURATION_S"));
  assert.equal(motion.MAX_BALL_DURATION_S, constant("MAX_BALL_DURATION_S"));
  assert.equal(motion.DASH_PERIOD, constant("DASH_PERIOD"));
  assert.equal(motion.PACKET_DASH_MIN, constant("PACKET_DASH_MIN"));
  assert.equal(motion.PACKET_DASH_MAX, constant("PACKET_DASH_MAX"));
  assert.equal(mine.IDLE_THRESHOLD_W, constant("IDLE_THRESHOLD_W"));
  // Pulse-count bands: the same threshold table.
  assert.match(src, /if \(magnitudeW < 750\) return 1;\s*if \(magnitudeW < 3000\) return 2;\s*if \(magnitudeW < 6000\) return 3;\s*return 4;/);
  assert.deepEqual([100, 750, 2999, 3000, 5999, 6000, 9000].map(motion.ballCountForMagnitude), [1, 2, 2, 3, 3, 4, 4]);
});
